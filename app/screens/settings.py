import json
import os
from threading import Thread
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.textfield import MDTextField
from kivy.clock import Clock
from kivy.lang import Builder
from services.connectorConfig import ensure_device_id, load_connector_config, save_connector_config
from services.pairingClient import PairingError, pair_device

Builder.load_string('''
<ApiKeyTxtbox>:
    mode: "outlined"
    readonly: True
<SettingsBox>:
    orientation: "vertical"
    MDBoxLayout:
        orientation: "horizontal"
        adaptive_height: True
        adaptive_width: True
        spacing: dp(2)
        pos_hint: {"center_x": .5}
        MDButton:
            theme_bg_color: "Custom"
            md_bg_color: "green"
            on_release: app.save_settings(self)
            MDButtonIcon:
                icon: "floppy"
                color: "white"
            MDButtonText:
                text: "Save"
                color: "white"
        MDButton:
            theme_bg_color: "Custom"
            md_bg_color: "black"
            on_release: app.reset_settings(self)
            MDButtonIcon:
                icon: "undo"
                color: "white"
            MDButtonText:
                text: "Reset"
                color: "white"
    MDScrollView:
        do_scroll_x: False
        MDBoxLayout:
            id: main_scroll_bx
            orientation: "vertical"
            adaptive_height: True
            spacing: dp(6)
            MDListItem:
                MDListItemLeadingIcon:
                    icon: "rocket-launch"
                MDListItemHeadlineText:
                    text: "Auto Start API Server"
                MDListItemSupportingText:
                    text: "Starts when app is launched"
                MDSwitch:
                    id: auto_start_sw
                    pos_hint: {"center_y": 0.5}
                    icon_active: "check"
                    icon_inactive: "close"
                    icon_active_color: "green"
                    track_color_active: "green"
                    on_release: app.save_settings(self, "switch")
            MDListItem:
                MDListItemLeadingIcon:
                    icon: "api"
                MDListItemHeadlineText:
                    text: "Port Number"
                MDListItemSupportingText:
                    text: "Needs a Stop-Start"
                MDListItemTertiaryText:
                    text: "Should be > 1024"
                MDTextField:
                    id: port_no_inp
                    mode: "filled"
                    input_filter: 'int'
            MDListItem:
                MDListItemLeadingIcon:
                    icon: "key"
                MDListItemHeadlineText:
                    text: "API Key"
                MDListItemSupportingText:
                    text: "Generate New API Key"
                MDListItemTertiaryText:
                    text: "Old key will not work"
                MDFabButton:
                    icon: "autorenew"
                    style: "small"
                    theme_bg_color: "Custom"
                    md_bg_color: "orange"
                    pos_hint: {'center_y': 0.5}
                    on_release: app.new_api_key_pop()
            MDLabel:
                text: "Remote Gateway"
                bold: True
                adaptive_height: True
            MDLabel:
                text: "Works over Wi-Fi or mobile data; the phone does not need to be on the same network as the API client."
                adaptive_height: True
                text_size: self.width, None
            MDTextField:
                id: remote_gateway_url
                mode: "outlined"
                hint_text: "Gateway URL (https://...)"
            MDTextField:
                id: remote_device_name
                mode: "outlined"
                hint_text: "Device name"
            MDTextField:
                id: remote_pairing_code
                mode: "outlined"
                hint_text: "6-digit pairing code"
                input_filter: 'int'
                max_text_length: 6
            MDTextField:
                id: remote_device_id
                mode: "outlined"
                hint_text: "Device ID"
                readonly: True
            MDListItem:
                MDListItemLeadingIcon:
                    icon: "lan-connect"
                MDListItemHeadlineText:
                    text: "Enable Remote Connector"
                MDListItemSupportingText:
                    text: "Outbound connection only; no inbound phone port required"
                MDSwitch:
                    id: remote_enabled_sw
                    pos_hint: {"center_y": 0.5}
                    icon_active: "check"
                    icon_inactive: "close"
                    on_active: root.set_remote_enabled(self.active)
            MDButton:
                style: "elevated"
                pos_hint: {"center_x": .5}
                on_release: root.pair_remote_device()
                MDButtonIcon:
                    icon: "link-variant"
                MDButtonText:
                    text: "Pair Device"
            MDLabel:
                id: remote_status_lbl
                text: "Not paired"
                adaptive_height: True
                halign: "center"
''')

class SettingsBox(MDBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs); self._remote_loading=False; self._status_event=None
    def on_kv_post(self, base_widget): Clock.schedule_once(self._load_remote_when_ready, 0)
    def _app(self): return MDApp.get_running_app()
    def _config_dir(self):
        app=self._app(); return getattr(app,"config_dir",None) if app else None
    def _load_remote_when_ready(self,_dt):
        config_dir=self._config_dir()
        if not config_dir: Clock.schedule_once(self._load_remote_when_ready,0.5); return
        config=load_connector_config(config_dir); had_id=bool(config.get("device_id")); config=ensure_device_id(config)
        if not had_id: save_connector_config(config_dir,config)
        self._remote_loading=True
        try:
            self.ids.remote_gateway_url.text=config.get("gateway_url",""); self.ids.remote_device_name.text=config.get("device_name","")
            self.ids.remote_device_id.text=config.get("device_id",""); self.ids.remote_enabled_sw.active=bool(config.get("enabled",False))
        finally: self._remote_loading=False
        self._set_status_from_config(config)
        if self._status_event is None: self._status_event=Clock.schedule_interval(self._poll_connector_status,2)
    def _set_status_from_config(self,config):
        self.ids.remote_status_lbl.text = "Not paired" if not config.get("device_credential") else ("Paired / connector disabled" if not config.get("enabled") else "Offline")
    def _poll_connector_status(self,_dt):
        app=self._app(); resp_path=getattr(app,"resp_path",None) if app else None
        if not resp_path or not os.path.exists(resp_path): return
        try:
            with open(resp_path,"r",encoding="utf-8") as fh: connector=json.load(fh).get("connector","")
        except Exception: return
        mapping={"disabled":"Paired / connector disabled","connecting":"Connecting","authenticating":"Connecting","online":"Online","auth_failed":"Authentication failed","stopped":"Offline"}
        self.ids.remote_status_lbl.text = "Offline" if connector.startswith("offline:") else mapping.get(connector,self.ids.remote_status_lbl.text)
    def _base_remote_config(self):
        config_dir=self._config_dir()
        if not config_dir: raise RuntimeError("application storage not ready")
        config=ensure_device_id(load_connector_config(config_dir)); config["gateway_url"]=self.ids.remote_gateway_url.text.strip().rstrip("/"); config["device_name"]=self.ids.remote_device_name.text.strip() or "OpenSMS Android"
        return config_dir,config
    def set_remote_enabled(self,active):
        if self._remote_loading: return
        try: config_dir,config=self._base_remote_config()
        except RuntimeError: return
        if active and not config.get("device_credential"):
            self._remote_loading=True; self.ids.remote_enabled_sw.active=False; self._remote_loading=False; self.ids.remote_status_lbl.text="Not paired"; return
        config["enabled"]=bool(active); save_connector_config(config_dir,config); self._set_status_from_config(config)
    def pair_remote_device(self):
        try: config_dir,config=self._base_remote_config()
        except RuntimeError: self.ids.remote_status_lbl.text="Storage not ready"; return
        code=self.ids.remote_pairing_code.text.strip(); self.ids.remote_pairing_code.text=""
        if len(code)!=6 or not code.isdigit(): self.ids.remote_status_lbl.text="Enter a valid 6-digit pairing code"; return
        if not config.get("gateway_url") or not config.get("device_name"): self.ids.remote_status_lbl.text="Gateway URL and device name are required"; return
        save_connector_config(config_dir,config); self.ids.remote_status_lbl.text="Pairing..."
        Thread(target=self._pair_worker,args=(config_dir,config,code),daemon=True).start()
    def _pair_worker(self,config_dir,config,code):
        try: result=pair_device(config["gateway_url"],code,config["device_id"],config["device_name"])
        except (PairingError,ValueError): Clock.schedule_once(lambda dt:self._pair_failed()); return
        Clock.schedule_once(lambda dt:self._pair_succeeded(config_dir,config,result))
    def _pair_failed(self): self.ids.remote_status_lbl.text="Pairing failed — verify URL/code and try again"
    def _pair_succeeded(self,config_dir,config,result):
        config["device_credential"]=result["device_credential"]; config["enabled"]=True; save_connector_config(config_dir,config); self._remote_loading=True
        try: self.ids.remote_enabled_sw.active=True; self.ids.remote_device_id.text=config["device_id"]
        finally: self._remote_loading=False
        self.ids.remote_status_lbl.text="Paired / connecting"

class ApiKeyTxtbox(MDTextField): pass
