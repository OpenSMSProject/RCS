from kivy.utils import platform

from os.path import join, exists
from threading import Thread

import json
import time

from services.postApi import PosiApiServer, set_config_path, set_api_os, set_api_logger
from services.logSvc import LogService
from services.remoteConnector import RemoteConnector
from services.smsApi import send_sms

app_name = "opensms"
resp_template = {
    "server": "none",
}
req_data = {}
api_started = False
log_obj = LogService(app_name, platform)

if platform == "android":
    from android.storage import app_storage_path
    base_path = app_storage_path()
else:
    from services.pathMgr import get_user_data_dir
    base_path = get_user_data_dir(app_name)

config_dir = join(base_path, 'config')
if not exists(config_dir):
    import os
    os.makedirs(config_dir, exist_ok=True)
set_config_path(config_dir)
set_api_os(platform)
set_api_logger(log_obj)
req_file = join(config_dir, "request.json")
resp_file = join(config_dir, "resp.json")

app_api_server = PosiApiServer()
remote_connector = RemoteConnector(config_dir, sms_sender=send_sms)


def write_resp():
    global resp_template
    with open(resp_file, "w") as rf:
        json.dump(resp_template, rf)


def read_req_file():
    global req_data
    if exists(req_file):
        try:
            with open(req_file, "r") as rf:
                req_data = json.load(rf)
        except Exception as e:
            print(f"Error while reading config from svc: {type(e).__name__}")


def api_server_control(api_stat: str):
    global api_started
    global resp_template
    global req_data
    if api_stat == "stop":
        app_api_server.stop()
        api_started = False
        resp_template["server"] = "stopped"
    elif api_stat == "start":
        app_api_server.start(req_data["port"])
        api_started = True
        resp_template["server"] = "started"
    Thread(target=write_resp, daemon=True).start()


def app_service_thread():
    global api_started

    write_resp()
    remote_connector.start()

    while True:
        read_req_file()
        server_stat = req_data.get("server", "")
        if not api_started and server_stat == "start":
            api_server_control("start")
        elif api_started and server_stat == "stop":
            api_server_control("stop")
        time.sleep(0.2)


if __name__ == "__main__":
    app_service_thread()
