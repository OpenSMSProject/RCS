import json
import os
import sys
import pytest
sys.path.insert(0,os.path.abspath('app'))
from services.connectorConfig import save_connector_config
from services.jobLedger import JobLedger
from services.remoteConnector import RemoteConnector

def make_connector(tmp_path,sender=lambda n,t:True):
    save_connector_config(str(tmp_path),{'enabled':True,'gateway_url':'wss://gateway.example.com/api/v1/device/connect','device_id':'osms-abcdef123456','device_name':'Phone','device_credential':'osmsdev_secret','heartbeat_seconds':20}); c=RemoteConnector(str(tmp_path),sms_sender=sender); sent=[]; c._send=lambda p:sent.append(p); return c,sent

def test_hello_includes_protocol_identity_and_credential(tmp_path):
    c,s=make_connector(tmp_path); c._send_hello(); assert s[0]['protocol']==1 and s[0]['device_id']=='osms-abcdef123456' and s[0]['credential']=='osmsdev_secret' and s[0]['app_version']=='0.1.0'

def test_ack_happens_before_sms_sender_and_success_is_persisted(tmp_path):
    events=[]; c,s=make_connector(tmp_path,lambda n,t:events.append('sender') or True); c._authenticated=True; c._send=lambda p:events.append(p['type']) or s.append(p); c._process_message({'type':'job','job_id':'job-3','command':'send_sms','number':'+5561999999999','text':'Teste'}); assert events[:2]==['job_ack','sender']; assert JobLedger(str(tmp_path/'remote-jobs.json')).get('job-3')['state']=='sent'

def test_sender_errors_are_safe(tmp_path):
    def boom(n,t): raise RuntimeError('secret message content')
    c,s=make_connector(tmp_path,boom); c._authenticated=True; c._process_message({'type':'job','job_id':'job-5','command':'send_sms','number':'+5561999999999','text':'Sensitive'}); assert s[-1]['error']=='sms_exception'; assert 'Sensitive' not in json.dumps(s[-1])

def test_duplicate_uncertain_state_is_suppressed(tmp_path):
    calls=[]; c,s=make_connector(tmp_path,lambda n,t:calls.append(1) or True); c._authenticated=True; c.ledger.mark('job-7','sending'); c._process_message({'type':'job','job_id':'job-7','command':'send_sms','number':'+5561999999999','text':'Teste'}); assert calls==[]; assert s[-1]['error']=='duplicate_suppressed_uncertain'

def test_plaintext_remote_transport_requires_explicit_dev_override(tmp_path,monkeypatch):
    c,_=make_connector(tmp_path); monkeypatch.delenv('OPENSMS_ALLOW_INSECURE_GATEWAY',raising=False)
    with pytest.raises(ValueError,match='secure'): c._device_ws_url('http://gateway.local')
    with pytest.raises(ValueError,match='secure'): c._device_ws_url('ws://gateway.local')
    monkeypatch.setenv('OPENSMS_ALLOW_INSECURE_GATEWAY','1'); assert c._device_ws_url('http://gateway.local')=='ws://gateway.local/api/v1/device/connect'
