import json
import os
import sys

sys.path.insert(0, os.path.abspath('app'))

from services.connectorConfig import save_connector_config
from services.jobLedger import JobLedger
from services.remoteConnector import RemoteConnector


def make_connector(tmp_path, sender=lambda n, t: True):
    save_connector_config(str(tmp_path), {
        'enabled': True,
        'gateway_url': 'wss://gateway.example.com/api/v1/device/connect',
        'device_id': 'osms-abcdef123456',
        'device_name': 'Phone',
        'device_credential': 'osmsdev_secret',
        'heartbeat_seconds': 20,
    })
    connector = RemoteConnector(str(tmp_path), sms_sender=sender)
    sent = []
    connector._send = lambda payload: sent.append(payload)
    return connector, sent


def test_hello_includes_protocol_identity_and_credential(tmp_path):
    connector, sent = make_connector(tmp_path)
    connector._send_hello()
    assert sent == [{
        'type': 'hello',
        'protocol': 1,
        'device_id': 'osms-abcdef123456',
        'credential': 'osmsdev_secret',
        'agent': 'opensms-android',
    }]


def test_job_is_rejected_before_gateway_authentication(tmp_path):
    calls = []
    connector, sent = make_connector(tmp_path, lambda n, t: calls.append((n, t)) or True)
    connector._process_message({'type': 'job', 'job_id': 'job-1', 'command': 'send_sms', 'number': '+5561999999999', 'text': 'Oi'})
    assert calls == []
    assert sent[-1]['state'] == 'failed'
    assert sent[-1]['error'] == 'not_authenticated'


def test_ping_yields_pong_and_malformed_json_is_ignored(tmp_path):
    connector, sent = make_connector(tmp_path)
    assert connector._process_raw('{not-json') is False
    connector._process_message({'type': 'ping'})
    assert sent[-1]['type'] == 'pong'


def test_unsupported_command_returns_safe_failure(tmp_path):
    connector, sent = make_connector(tmp_path)
    connector._authenticated = True
    connector._process_message({'type': 'job', 'job_id': 'job-2', 'command': 'shell', 'number': '+5561999999999', 'text': 'x'})
    assert sent[-1]['type'] == 'job_result'
    assert sent[-1]['job_id'] == 'job-2'
    assert sent[-1]['state'] == 'failed'
    assert sent[-1]['ok'] is False
    assert sent[-1]['error'] == 'unsupported_command'


def test_ack_happens_before_sms_sender_and_success_is_persisted(tmp_path):
    events = []
    connector, sent = make_connector(tmp_path, lambda n, t: events.append('sender') or True)
    connector._authenticated = True
    connector._send = lambda payload: events.append(payload['type']) or sent.append(payload)
    connector._process_message({'type': 'job', 'job_id': 'job-3', 'command': 'send_sms', 'number': '+5561999999999', 'text': 'Teste'})
    assert events[:2] == ['job_ack', 'sender']
    assert sent[-1]['state'] == 'sent'
    record = JobLedger(str(tmp_path / 'remote-jobs.json')).get('job-3')
    assert record['state'] == 'sent'
    assert record['result']['state'] == 'sent'


def test_sender_false_or_exception_returns_failed_with_safe_code(tmp_path):
    connector, sent = make_connector(tmp_path, lambda n, t: False)
    connector._authenticated = True
    connector._process_message({'type': 'job', 'job_id': 'job-4', 'command': 'send_sms', 'number': '+5561999999999', 'text': 'Teste'})
    assert sent[-1]['state'] == 'failed'
    assert sent[-1]['error'] == 'sms_send_failed'

    def boom(n, t):
        raise RuntimeError('secret message content')

    connector2, sent2 = make_connector(tmp_path / 'other', boom)
    connector2._authenticated = True
    connector2._process_message({'type': 'job', 'job_id': 'job-5', 'command': 'send_sms', 'number': '+5561999999999', 'text': 'Sensitive'})
    assert sent2[-1]['state'] == 'failed'
    assert sent2[-1]['error'] == 'sms_exception'
    assert 'Sensitive' not in json.dumps(sent2[-1])


def test_payload_limits_reject_invalid_number_and_text(tmp_path):
    connector, sent = make_connector(tmp_path)
    connector._authenticated = True
    for payload in [
        {'type': 'job', 'job_id': '', 'command': 'send_sms', 'number': '+5561999999999', 'text': 'x'},
        {'type': 'job', 'job_id': 'a', 'command': 'send_sms', 'number': '1' * 65, 'text': 'x'},
        {'type': 'job', 'job_id': 'b', 'command': 'send_sms', 'number': '+5561999999999', 'text': ''},
        {'type': 'job', 'job_id': 'c', 'command': 'send_sms', 'number': '+5561999999999', 'text': 'x' * 4001},
    ]:
        connector._process_message(payload)
        assert sent[-1]['state'] == 'failed'
        assert sent[-1]['error'] == 'invalid_payload'


def test_duplicate_sent_returns_prior_result_without_resending(tmp_path):
    calls = []
    connector, sent = make_connector(tmp_path, lambda n, t: calls.append(1) or True)
    connector._authenticated = True
    connector.ledger.mark('job-6', 'sent', {'type': 'job_result', 'job_id': 'job-6', 'state': 'sent', 'error': None})
    connector._process_message({'type': 'job', 'job_id': 'job-6', 'command': 'send_sms', 'number': '+5561999999999', 'text': 'Teste'})
    assert calls == []
    assert sent[-1]['state'] == 'sent'


def test_duplicate_uncertain_state_is_suppressed(tmp_path):
    for state in ('accepted', 'sending', 'ambiguous'):
        child = tmp_path / state
        calls = []
        connector, sent = make_connector(child, lambda n, t: calls.append(1) or True)
        connector._authenticated = True
        connector.ledger.mark('job-7', state)
        connector._process_message({'type': 'job', 'job_id': 'job-7', 'command': 'send_sms', 'number': '+5561999999999', 'text': 'Teste'})
        assert calls == []
        assert sent[-1]['state'] == 'failed'
        assert sent[-1]['error'] == 'duplicate_suppressed_uncertain'


def test_ack_and_result_include_device_identity_and_ok_flag(tmp_path):
    connector, sent = make_connector(tmp_path)
    connector._authenticated = True
    connector._process_message({'type': 'job', 'job_id': 'job-8', 'command': 'send_sms', 'number': '+5561999999999', 'text': 'Teste'})
    ack = sent[-2]
    result = sent[-1]
    assert ack['device_id'] == 'osms-abcdef123456'
    assert result['device_id'] == 'osms-abcdef123456'
    assert result['ok'] is True
