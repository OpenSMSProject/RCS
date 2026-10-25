import os
import sys
sys.path.insert(0, os.path.abspath('gateway'))
from fastapi.testclient import TestClient
from opensms_gateway.app import create_app
from opensms_gateway.config import GatewaySettings
from opensms_gateway.storage import GatewayStore

def auth(token): return {'Authorization': f'Bearer {token}'}

def test_pair_and_message_routes_are_rate_limited(tmp_path):
    settings=GatewaySettings(db_path=str(tmp_path/'gateway.sqlite3'),api_token='api-token',admin_token='admin-token',pairing_ttl_seconds=300,pairing_rate_limit_per_minute=1,message_rate_limit_per_minute=1)
    store=GatewayStore(settings.db_path); store.create_device('osms-abcdef123456','Phone','secret'); client=TestClient(create_app(settings=settings,store=store))
    assert client.post('/api/v1/devices/pair',json={'pairing_code':'000000','device_id':'osms-one123456789','name':'One'}).status_code==400
    assert client.post('/api/v1/devices/pair',json={'pairing_code':'000001','device_id':'osms-two123456789','name':'Two'}).status_code==429
    payload={'device_id':'osms-abcdef123456','to':'+5561999999999','text':'one'}; assert client.post('/api/v1/messages',headers=auth('api-token'),json=payload).status_code==202
    payload['text']='two'; assert client.post('/api/v1/messages',headers=auth('api-token'),json=payload).status_code==429
