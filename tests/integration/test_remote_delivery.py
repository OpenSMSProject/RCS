import os
import sys
import time
from fastapi.testclient import TestClient
sys.path.insert(0, os.path.abspath('app')); sys.path.insert(0, os.path.abspath('gateway'))
from services.connectorConfig import save_connector_config
from services.remoteConnector import RemoteConnector
from opensms_gateway.app import create_app
from opensms_gateway.config import GatewaySettings
from opensms_gateway.storage import GatewayStore

def wait_message(store,message_id,state,timeout=1.5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        record=store.get_message(message_id)
        if record and record['state']==state:return record
        time.sleep(0.005)
    return store.get_message(message_id)

def build_gateway(db_path):
    settings=GatewaySettings(db_path=str(db_path),api_token='api-token',admin_token='admin-token',pairing_ttl_seconds=300)
    store=GatewayStore(str(db_path)); return TestClient(create_app(settings=settings,store=store)),store

def headers(token='api-token'): return {'Authorization':f'Bearer {token}'}

def pair_phone(client,config_dir,device_id='osms-abcdef123456'):
    code=client.post('/api/v1/pairing-codes',headers=headers('admin-token')).json()['pairing_code']
    paired=client.post('/api/v1/devices/pair',json={'pairing_code':code,'device_id':device_id,'name':'Integration Phone'}); assert paired.status_code==201
    cred=paired.json()['device_credential']; save_connector_config(str(config_dir),{'enabled':True,'gateway_url':'https://gateway.example.test','device_id':device_id,'device_name':'Integration Phone','device_credential':cred,'heartbeat_seconds':20}); return cred

def attach(ws,config_dir,sender):
    c=RemoteConnector(str(config_dir),sms_sender=sender); c._send=lambda p:ws.send_json(p); c._send_hello(); ok=ws.receive_json(); assert ok['type']=='hello_ok'; c._process_message(ok); return c

def test_end_to_end_happy_path_pairs_dispatches_and_reports_sent(tmp_path):
    client,store=build_gateway(tmp_path/'g.sqlite3'); cfg=tmp_path/'phone'; pair_phone(client,cfg); sent=[]
    with client.websocket_connect('/api/v1/device/connect') as ws:
        c=attach(ws,cfg,lambda n,t:sent.append((n,t)) or True); r=client.post('/api/v1/messages',headers=headers(),json={'device_id':'osms-abcdef123456','to':'+5561999999999','text':'Mensagem remota'}); mid=r.json()['message_id']; c._process_message(ws.receive_json()); assert wait_message(store,mid,'sent')['state']=='sent'
    assert sent==[('+5561999999999','Mensagem remota')]

def test_offline_submission_is_delivered_after_reconnect(tmp_path):
    client,store=build_gateway(tmp_path/'g.sqlite3'); cfg=tmp_path/'phone'; pair_phone(client,cfg); sent=[]
    mid=client.post('/api/v1/messages',headers=headers(),json={'device_id':'osms-abcdef123456','to':'+5561999999998','text':'Offline queue'}).json()['message_id']; assert store.get_message(mid)['state']=='waiting_device'
    with client.websocket_connect('/api/v1/device/connect') as ws:
        c=attach(ws,cfg,lambda n,t:sent.append((n,t)) or True); c._process_message(ws.receive_json()); assert wait_message(store,mid,'sent')['state']=='sent'
    assert len(sent)==1

def test_gateway_restart_recovers_pending_sqlite_job(tmp_path):
    db=tmp_path/'g.sqlite3'; cfg=tmp_path/'phone'; c1,s1=build_gateway(db); cred=pair_phone(c1,cfg); mid=c1.post('/api/v1/messages',headers=headers(),json={'device_id':'osms-abcdef123456','to':'+5561999999997','text':'Survive restart'}).json()['message_id']; c1.close(); s1.close(); c2,s2=build_gateway(db); assert s2.verify_device_credential('osms-abcdef123456',cred)
    with c2.websocket_connect('/api/v1/device/connect') as ws:
        c=attach(ws,cfg,lambda n,t:True); c._process_message(ws.receive_json()); assert wait_message(s2,mid,'sent')['state']=='sent'

def test_uncertain_duplicate_is_suppressed_after_phone_restart(tmp_path):
    client,store=build_gateway(tmp_path/'g.sqlite3'); cfg=tmp_path/'phone'; pair_phone(client,cfg); sends=[]
    with client.websocket_connect('/api/v1/device/connect') as ws:
        c=attach(ws,cfg,lambda n,t:sends.append((n,t)) or True); mid=client.post('/api/v1/messages',headers=headers(),json={'device_id':'osms-abcdef123456','to':'+5561999999996','text':'Ambiguous'}).json()['message_id']; job=ws.receive_json(); c.ledger.mark(mid,'accepted'); ws.send_json({'type':'job_ack','job_id':mid,'device_id':'osms-abcdef123456'}); c.ledger.mark(mid,'sending'); assert c.sms_sender(job['number'],job['text']); assert wait_message(store,mid,'acknowledged')['state']=='acknowledged'
    restarted=RemoteConnector(str(cfg),sms_sender=lambda n,t:sends.append(('DUPLICATE',t)) or True); assert restarted.ledger.get(mid)['state']=='ambiguous'
    with client.websocket_connect('/api/v1/device/connect') as ws:
        restarted._send=lambda p:ws.send_json(p); restarted._send_hello(); restarted._process_message(ws.receive_json()); restarted._process_message(ws.receive_json()); assert wait_message(store,mid,'failed')['error_code']=='duplicate_suppressed_uncertain'
    assert sends==[('+5561999999996','Ambiguous')]
