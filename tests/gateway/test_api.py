import importlib
import os
import sys
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, os.path.abspath('gateway'))
from opensms_gateway.config import GatewaySettings
from opensms_gateway.storage import GatewayStore

def build(tmp_path):
    try: module = importlib.import_module('opensms_gateway.app')
    except ModuleNotFoundError: pytest.fail('opensms_gateway.app is not implemented')
    settings = GatewaySettings(db_path=str(tmp_path/'gateway.sqlite3'), api_token='api-token', admin_token='admin-token', pairing_ttl_seconds=300)
    store = GatewayStore(settings.db_path); return TestClient(module.create_app(settings=settings, store=store)), store

def auth(token): return {'Authorization': f'Bearer {token}'}

def test_health_is_public_but_admin_and_api_routes_are_protected(tmp_path):
    client,_=build(tmp_path); assert client.get('/healthz').status_code==200; assert client.get('/readyz').status_code==200
    assert client.post('/api/v1/pairing-codes').status_code==401; assert client.get('/api/v1/devices').status_code==401
    assert client.post('/api/v1/messages',json={}).status_code==401
    assert client.post('/api/v1/pairing-codes',headers=auth('api-token')).status_code==403
    assert client.post('/api/v1/messages',headers=auth('admin-token'),json={}).status_code==403

def test_pairing_code_is_one_use_and_credential_is_returned_once(tmp_path):
    client,store=build(tmp_path); created=client.post('/api/v1/pairing-codes',headers=auth('admin-token')); assert created.status_code==201
    code=created.json()['pairing_code']; payload={'pairing_code':code,'device_id':'osms-abcdef123456','name':'Galaxy A32'}
    paired=client.post('/api/v1/devices/pair',json=payload); assert paired.status_code==201; body=paired.json(); assert body['device_credential'].startswith('osmsdev_')
    assert store.verify_device_credential(body['device_id'],body['device_credential']) is True
    again=client.post('/api/v1/devices/pair',json={**payload,'device_id':'osms-another12345'}); assert again.status_code==400; assert 'device_credential' not in again.text

def test_device_list_never_exposes_credential_hash(tmp_path):
    client,store=build(tmp_path); store.create_device('osms-abcdef123456','Phone','top-secret')
    response=client.get('/api/v1/devices',headers=auth('admin-token')); assert response.status_code==200; assert 'top-secret' not in response.text; assert 'credential_hash' not in response.text

def test_message_validation_persistence_and_idempotency(tmp_path):
    client,store=build(tmp_path); store.create_device('osms-abcdef123456','Phone','secret')
    headers={**auth('api-token'),'Idempotency-Key':'request-123'}; payload={'device_id':'osms-abcdef123456','to':'+5561999999999','text':'Teste'}
    first=client.post('/api/v1/messages',headers=headers,json=payload); assert first.status_code==202; mid=first.json()['message_id']; assert store.get_message(mid)['state']=='waiting_device'
    second=client.post('/api/v1/messages',headers=headers,json=payload); assert second.json()['message_id']==mid; assert client.get(f'/api/v1/messages/{mid}',headers=auth('api-token')).status_code==200

def test_message_rejects_bad_phone_empty_or_oversized_text_and_bad_device(tmp_path):
    client,store=build(tmp_path); store.create_device('osms-abcdef123456','Phone','secret'); headers=auth('api-token'); base={'device_id':'osms-abcdef123456','to':'+5561999999999','text':'ok'}
    for changes in ({'to':'61999999999'},{'to':'+123'},{'text':''},{'text':'x'*4001}): assert client.post('/api/v1/messages',headers=headers,json={**base,**changes}).status_code==422
    assert client.post('/api/v1/messages',headers=headers,json={**base,'device_id':'osms-unknown12345'}).status_code==404
    store.revoke_device('osms-abcdef123456'); assert client.post('/api/v1/messages',headers=headers,json=base).status_code==409

def test_failed_pairing_does_not_consume_one_time_code(tmp_path):
    client,store=build(tmp_path); store.create_device('osms-existing12345','Existing','secret'); code=client.post('/api/v1/pairing-codes',headers=auth('admin-token')).json()['pairing_code']
    assert client.post('/api/v1/devices/pair',json={'pairing_code':code,'device_id':'osms-existing12345','name':'Duplicate'}).status_code==409
    assert client.post('/api/v1/devices/pair',json={'pairing_code':code,'device_id':'osms-fresh1234567','name':'Fresh'}).status_code==201

def test_admin_can_revoke_device(tmp_path):
    client,store=build(tmp_path); store.create_device('osms-abcdef123456','Phone','secret')
    assert client.delete('/api/v1/devices/osms-abcdef123456',headers=auth('admin-token')).status_code==204; assert store.get_device('osms-abcdef123456')['enabled'] is False
