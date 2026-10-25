import os
import sys

import pytest

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.config import SaaSSettings


def clear_saas_env(monkeypatch):
    for name in (
        "OPENSMS_SAAS_ENABLED",
        "OPENSMS_SAAS_DATABASE_URL",
        "OPENSMS_SAAS_SESSION_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def test_saas_is_disabled_by_default_and_needs_no_database(monkeypatch):
    clear_saas_env(monkeypatch)
    settings = SaaSSettings.from_env()
    assert settings.enabled is False
    assert settings.database_url is None
    assert settings.session_secret is None


def test_enabled_saas_requires_database_url(monkeypatch):
    clear_saas_env(monkeypatch)
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "1")
    monkeypatch.setenv("OPENSMS_SAAS_SESSION_SECRET", "s" * 48)
    with pytest.raises(ValueError, match="OPENSMS_SAAS_DATABASE_URL"):
        SaaSSettings.from_env()


def test_enabled_saas_requires_strong_session_secret(monkeypatch):
    clear_saas_env(monkeypatch)
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "1")
    monkeypatch.setenv("OPENSMS_SAAS_DATABASE_URL", "postgresql+psycopg://u:p@db/opensms")
    monkeypatch.setenv("OPENSMS_SAAS_SESSION_SECRET", "short")
    with pytest.raises(ValueError, match="session secret"):
        SaaSSettings.from_env()


def test_enabled_saas_accepts_valid_configuration(monkeypatch):
    clear_saas_env(monkeypatch)
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "true")
    monkeypatch.setenv("OPENSMS_SAAS_DATABASE_URL", "postgresql+psycopg://u:p@db/opensms")
    monkeypatch.setenv("OPENSMS_SAAS_SESSION_SECRET", "x" * 48)
    settings = SaaSSettings.from_env()
    assert settings.enabled is True
    assert settings.database_url.endswith("/opensms")
    assert settings.session_secret == "x" * 48
