import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath('gateway'))


def store_cls():
    try:
        module = importlib.import_module('opensms_gateway.storage')
    except ModuleNotFoundError:
        pytest.fail('opensms_gateway.storage is not implemented')
    return module.GatewayStore


def test_pairing_code_is_single_use_and_expiring(tmp_path):
    Store = store_cls()
    store = Store(str(tmp_path / 'gateway.sqlite3'))
    store.create_pairing_code('123456', ttl_seconds=60, now=1000)
    assert store.consume_pairing_code('123456', now=1030) is True
    assert store.consume_pairing_code('123456', now=1031) is False

    store.create_pairing_code('654321', ttl_seconds=10, now=2000)
    assert store.consume_pairing_code('654321', now=2011) is False


def test_device_credential_is_hashed_and_revocable(tmp_path):
    Store = store_cls()
    store = Store(str(tmp_path / 'gateway.sqlite3'))
    store.create_device('osms-abc', 'Phone', 'osmsdev_raw_secret')
    device = store.get_device('osms-abc', include_secret_hash=True)
    assert 'osmsdev_raw_secret' not in device['credential_hash']
    assert store.verify_device_credential('osms-abc', 'osmsdev_raw_secret') is True
    store.revoke_device('osms-abc')
    assert store.verify_device_credential('osms-abc', 'osmsdev_raw_secret') is False
    assert store.get_device('osms-abc')['enabled'] is False


def test_message_idempotency_and_persistence_survive_reopen(tmp_path):
    Store = store_cls()
    path = str(tmp_path / 'gateway.sqlite3')
    store = Store(path)
    store.create_device('osms-abc', 'Phone', 'secret')
    first = store.create_message('osms-abc', '+5561999999999', 'Oi', idempotency_key='idem-1')
    again = store.create_message('osms-abc', '+5561999999999', 'Oi', idempotency_key='idem-1')
    assert again['message_id'] == first['message_id']
    reopened = Store(path)
    assert reopened.get_message(first['message_id'])['text'] == 'Oi'


def test_state_transitions_and_dispatchable_recovery(tmp_path):
    Store = store_cls()
    path = str(tmp_path / 'gateway.sqlite3')
    store = Store(path)
    store.create_device('osms-abc', 'Phone', 'secret')

    queued = store.create_message('osms-abc', '+5561999999999', 'q')
    acknowledged = store.create_message('osms-abc', '+5561999999998', 'a')
    terminal = store.create_message('osms-abc', '+5561999999997', 's')

    store.transition_message(acknowledged['message_id'], 'dispatching')
    store.transition_message(acknowledged['message_id'], 'acknowledged')
    store.transition_message(terminal['message_id'], 'dispatching')
    store.transition_message(terminal['message_id'], 'acknowledged')
    store.transition_message(terminal['message_id'], 'sent')

    reopened = Store(path)
    dispatchable = {m['message_id'] for m in reopened.list_dispatchable('osms-abc')}
    assert queued['message_id'] in dispatchable
    assert acknowledged['message_id'] in dispatchable
    assert terminal['message_id'] not in dispatchable
    assert reopened.get_message(terminal['message_id'])['completed_at'] is not None


def test_invalid_transition_is_rejected(tmp_path):
    Store = store_cls()
    store = Store(str(tmp_path / 'gateway.sqlite3'))
    store.create_device('osms-abc', 'Phone', 'secret')
    msg = store.create_message('osms-abc', '+5561999999999', 'Oi')
    store.transition_message(msg['message_id'], 'dispatching')
    store.transition_message(msg['message_id'], 'acknowledged')
    store.transition_message(msg['message_id'], 'sent')
    with pytest.raises(ValueError):
        store.transition_message(msg['message_id'], 'dispatching')
