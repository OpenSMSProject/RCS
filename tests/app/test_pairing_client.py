import io
import json
import os
import sys
from urllib.error import HTTPError, URLError
import pytest
sys.path.insert(0, os.path.abspath('app'))

def module():
    try:
        from services import pairingClient
        return pairingClient
    except ImportError: pytest.fail('services.pairingClient is not implemented')

class FakeResponse:
    def __init__(self,payload,status=201): self.payload=json.dumps(payload).encode(); self.status=status
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return self.payload

def test_pair_device_normalizes_https_url_and_posts_expected_json(monkeypatch):
    pc=module(); seen={}
    def fake_urlopen(request,timeout):
        seen['url']=request.full_url; seen['body']=json.loads(request.data.decode()); seen['timeout']=timeout
        return FakeResponse({'device_id':'osms-abc123456789','device_credential':'osmsdev_secret'})
    monkeypatch.setattr(pc.request,'urlopen',fake_urlopen); result=pc.pair_device('https://gateway.example.com/','123456','osms-abc123456789','Phone',timeout=7)
    assert seen['url']=='https://gateway.example.com/api/v1/devices/pair'; assert seen['timeout']==7; assert result['device_credential']=='osmsdev_secret'

def test_plain_http_is_rejected_unless_explicit_dev_override(monkeypatch):
    pc=module(); monkeypatch.delenv('OPENSMS_ALLOW_INSECURE_GATEWAY',raising=False)
    with pytest.raises(ValueError,match='HTTPS'): pc.pair_device('http://gateway.local','123456','osms-abc123456789','Phone')

def test_timeout_and_http_errors_are_safe_and_never_include_response_secret(monkeypatch):
    pc=module(); secret='osmsdev_MUST_NOT_LEAK'
    def http_error(*args,**kwargs): raise HTTPError(url='https://gateway.example.com/api/v1/devices/pair',code=500,msg='error',hdrs=None,fp=io.BytesIO((secret+' server detail').encode()))
    monkeypatch.setattr(pc.request,'urlopen',http_error)
    with pytest.raises(pc.PairingError) as exc: pc.pair_device('https://gateway.example.com','123456','osms-abc123456789','Phone')
    assert secret not in str(exc.value)
    monkeypatch.setattr(pc.request,'urlopen',lambda *a,**k: (_ for _ in ()).throw(URLError('timed out secret')))
    with pytest.raises(pc.PairingError) as exc2: pc.pair_device('https://gateway.example.com','123456','osms-abc123456789','Phone')
    assert 'timed out secret' not in str(exc2.value)

def test_invalid_success_payload_is_rejected_without_echoing_data(monkeypatch):
    pc=module(); monkeypatch.setattr(pc.request,'urlopen',lambda *a,**k:FakeResponse({'device_credential':'secret-only'}))
    with pytest.raises(pc.PairingError,match='invalid gateway response'): pc.pair_device('https://gateway.example.com','123456','osms-abc123456789','Phone')
