import os
import re
import sys

sys.path.insert(0, os.path.abspath('app'))

from services import connectorConfig as cc


def test_defaults_include_remote_identity_fields(tmp_path):
    cfg = cc.load_connector_config(str(tmp_path))
    assert cfg == {
        'enabled': False,
        'gateway_url': '',
        'device_id': '',
        'device_name': '',
        'device_credential': '',
        'heartbeat_seconds': 20,
    }


def test_save_persists_enabled_url_name_and_credential(tmp_path):
    cc.save_connector_config(str(tmp_path), {
        'enabled': True,
        'gateway_url': 'https://gateway.example.com',
        'device_name': 'Galaxy A32',
        'device_credential': 'osmsdev_secret_value',
        'heartbeat_seconds': 5,
    })
    cfg = cc.load_connector_config(str(tmp_path))
    assert cfg['enabled'] is True
    assert cfg['gateway_url'] == 'https://gateway.example.com'
    assert cfg['device_name'] == 'Galaxy A32'
    assert cfg['device_credential'] == 'osmsdev_secret_value'
    assert cfg['heartbeat_seconds'] == 10


def test_ensure_device_id_generates_once_and_preserves_it():
    cfg = dict(cc.DEFAULT_CONNECTOR_CONFIG)
    first = cc.ensure_device_id(cfg)
    assert re.fullmatch(r'osms-[0-9a-f]{12}', first['device_id'])
    second = cc.ensure_device_id(first)
    assert second['device_id'] == first['device_id']


def test_malformed_json_falls_back_without_leaking_file_contents(tmp_path, capsys):
    secret = 'osmsdev_SUPER_SECRET'
    (tmp_path / 'connector.json').write_text('{"device_credential":"%s",BROKEN' % secret)
    cfg = cc.load_connector_config(str(tmp_path))
    captured = capsys.readouterr().out
    assert cfg.get('device_credential', '') == ''
    assert secret not in captured
