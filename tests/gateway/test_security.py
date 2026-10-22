import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath('gateway'))


def security_module():
    try:
        return importlib.import_module('opensms_gateway.security')
    except ModuleNotFoundError:
        pytest.fail('opensms_gateway.security is not implemented')


def config_module():
    try:
        return importlib.import_module('opensms_gateway.config')
    except ModuleNotFoundError:
        pytest.fail('opensms_gateway.config is not implemented')


def test_new_secret_is_prefixed_unique_and_high_entropy():
    sec = security_module()
    one = sec.new_secret('osmsdev')
    two = sec.new_secret('osmsdev')
    assert one.startswith('osmsdev_')
    assert len(one) >= 40
    assert one != two


def test_hash_secret_hides_raw_and_verifies_correctly():
    sec = security_module()
    raw = 'osmsdev_super_secret_value'
    encoded = sec.hash_secret(raw)
    assert raw not in encoded
    assert sec.verify_secret(raw, encoded) is True
    assert sec.verify_secret('wrong', encoded) is False


def test_verify_secret_uses_compare_digest(monkeypatch):
    sec = security_module()
    encoded = sec.hash_secret('secret')
    called = []
    original = sec.secrets.compare_digest

    def tracked(left, right):
        called.append(True)
        return original(left, right)

    monkeypatch.setattr(sec.secrets, 'compare_digest', tracked)
    assert sec.verify_secret('secret', encoded) is True
    assert called


def test_settings_require_api_and_admin_tokens(monkeypatch, tmp_path):
    cfg = config_module()
    monkeypatch.delenv('OPENSMS_API_TOKEN', raising=False)
    monkeypatch.delenv('OPENSMS_ADMIN_TOKEN', raising=False)
    with pytest.raises(ValueError):
        cfg.GatewaySettings.from_env()

    monkeypatch.setenv('OPENSMS_API_TOKEN', 'api-token')
    monkeypatch.setenv('OPENSMS_ADMIN_TOKEN', 'admin-token')
    monkeypatch.setenv('OPENSMS_DB_PATH', str(tmp_path / 'db.sqlite3'))
    settings = cfg.GatewaySettings.from_env()
    assert settings.db_path == str(tmp_path / 'db.sqlite3')
    assert settings.api_token == 'api-token'
    assert settings.admin_token == 'admin-token'
    assert settings.pairing_ttl_seconds == 300
