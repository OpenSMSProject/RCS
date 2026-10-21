import hashlib
import secrets
import asyncio
from threading import Thread
from os.path import join, exists
import json
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import uvicorn
from services.smsApi import send_sms
from services.logSvc import LogService
app_name='opensms'; platform='linux'; logger=None; config_dir='./config'
def set_config_path(config_path:str):
    global config_dir; config_dir=config_path
def set_api_os(os_flavour:str):
    global platform; platform=os_flavour
def set_api_logger(log_obj:LogService):
    global logger; logger=log_obj
def log_activities(message:str):
    if logger: Thread(target=logger.write_log,kwargs={'message':message},daemon=True).start()
def hash_api_key(raw_key:str)->str:return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()
def generate_new_api_key()->str:
    raw=f"osms_{secrets.token_urlsafe(32)}"; data={hash_api_key(raw):{'name':'opensms','scopes':['sms:write']}}
    with open(join(config_dir,'keys.json'),'w') as kf:json.dump(data,kf)
    print('Created/updated the API key'); log_activities('Created/updated the API key'); return raw
def get_api_keys()->dict:
    path=join(config_dir,'keys.json')
    if exists(path):
        with open(path,'r') as kf:return json.load(kf)
    return {}
class SmsData(BaseModel):
    number:str; text:str; sub_text:str|None=None
class ControlData(BaseModel): api:str
app=FastAPI(); security=HTTPBearer()
class PosiApiServer:
    def __init__(self,host='0.0.0.0',port=9292):self.host=host;self.port=port;self.kivyCallback=None;self.server=None;self.thread=None
    def set_control_caller(self,callback=None):self.controlCallback=callback
    def set_kivy_caller(self,callback=None):self.kivyCallback=callback
    def _run(self,port=None):
        self.server=uvicorn.Server(uvicorn.Config(app,host=self.host,port=port if port else self.port,log_level='info',loop='asyncio'));app.state.server=self;asyncio.run(self.server.serve())
    def start(self,port=None):
        if self.thread and self.thread.is_alive():print('Server already running');return
        self.thread=Thread(target=self._run,kwargs={'port':port},daemon=True);self.thread.start();print('FastAPI started')
    def stop(self):
        if self.server:self.server.should_exit=True
        if self.thread:self.thread.join(timeout=5)
        self.server=None;self.thread=None
async def verify_api_key(request:Request,credentials:HTTPAuthorizationCredentials=Depends(security))->dict:
    client_ip=request.client.host if request.client else 'unknown';raw=credentials.credentials;hashed=hash_api_key(raw);info=get_api_keys().get(hashed)
    if not info or not secrets.compare_digest(hashed,hash_api_key(raw)):
        print(f'Authentication failed from IP: {client_ip}');log_activities(f'Authentication failed from IP: {client_ip}');raise HTTPException(status_code=401,detail='Invalid or expired API key')
    return info
@app.post('/sms/')
async def process_sms_req(item:SmsData,request:Request,client:dict=Depends(verify_api_key)):
    server=request.app.state.server;client_ip=request.client.host if request.client else 'unknown';print(f'Authenticated request from: {client_ip}');log_activities(f'Authenticated request from: {client_ip}');stat=send_sms(item.number,item.text)
    if stat:print('SMS successfully sent');log_activities('SMS successfully sent')
    else:print('SMS failed');log_activities('SMS failed')
    if server.kivyCallback:Thread(target=server.kivyCallback,kwargs={'stat':stat},daemon=True).start()
    return {'stat':stat}
@app.post('/control/')
async def internal_control(item:ControlData,request:Request):return item
if __name__=='__main__':PosiApiServer().start()
