import os
import sys
import time
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
sys.path.insert(0,os.path.abspath('gateway'))
from opensms_gateway.app import create_app
from opensms_gateway.config import GatewaySettings
from opensms_gateway.storage import GatewayStore

def build(tmp_path,timeout=60):
    settings=GatewaySettings(db_path=str(tmp_path/'g.sqlite3'),api_token='api-token',admin_token='admin-token',heartbeat_timeout_seconds=timeout); store=GatewayStore(settings.db_path); return TestClient(create_app(settings=settings,store=store)),store

def hello(credential='device-secret'): return {'type':'hello','protocol':1,'device_id':'osms-abcdef123456','credential':credential,'agent':'opensms-android'}
def wait_state(store,mid,state):
    deadline=time.monotonic()+1
    while time.monotonic()<deadline:
        if store.get_message(mid)['state']==state:return state
        time.sleep(.005)
    return store.get_message(mid)['state']

def test_invalid_or_revoked_credential_gets_no_jobs(tmp_path):
    client,store=build(tmp_path); store.create_device('osms-abcdef123456','Phone','device-secret'); store.create_message('osms-abcdef123456','+5561999999999','q')
    with client.websocket_connect('/api/v1/device/connect') as ws:
        ws.send_json(hello('wrong')); assert ws.receive_json()['type']=='hello_error'

def test_authenticated_device_receives_queued_job_ack_and_result(tmp_path):
    client,store=build(tmp_path); store.create_device('osms-abcdef123456','Phone','device-secret'); msg=store.create_message('osms-abcdef123456','+5561999999999','Oi')
    with client.websocket_connect('/api/v1/device/connect') as ws:
        ws.send_json(hello()); assert ws.receive_json()['type']=='hello_ok'; job=ws.receive_json(); assert job['job_id']==msg['message_id']; ws.send_json({'type':'job_ack','job_id':msg['message_id'],'device_id':'osms-abcdef123456'}); assert wait_state(store,msg['message_id'],'acknowledged')=='acknowledged'; ws.send_json({'type':'job_result','job_id':msg['message_id'],'device_id':'osms-abcdef123456','state':'sent','ok':True,'error':None}); assert wait_state(store,msg['message_id'],'sent')=='sent'

def test_stale_device_session_is_closed_after_heartbeat_timeout(tmp_path):
    client,store=build(tmp_path,.05); store.create_device('osms-abcdef123456','Phone','device-secret')
    with client.websocket_connect('/api/v1/device/connect') as ws:
        ws.send_json(hello()); assert ws.receive_json()['type']=='hello_ok'
        with pytest.raises(WebSocketDisconnect): ws.receive_json()
    assert store.get_device('osms-abcdef123456')['online'] is False
