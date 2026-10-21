import json
import random
import threading
import time
from typing import Optional

import websocket

from services.connectorConfig import load_connector_config


class RemoteConnector:
    """Outbound-only connector used by the Android background service."""

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws = None
        self.status = "stopped"

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self.status = "stopped"

    def _send(self, payload: dict):
        self._ws.send(json.dumps(payload, separators=(",", ":")))

    def _heartbeat_loop(self, device_id: str, interval: int):
        while not self._stop.wait(interval):
            try:
                self._send({
                    "type": "heartbeat",
                    "device_id": device_id,
                    "timestamp": int(time.time()),
                })
            except Exception:
                return

    def _connect_once(self, config: dict):
        gateway_url = str(config.get("gateway_url", "")).strip()
        device_id = str(config.get("device_id", "")).strip()
        interval = max(10, int(config.get("heartbeat_seconds", 20)))

        self.status = "connecting"
        self._ws = websocket.create_connection(gateway_url, timeout=30)
        self._send({
            "type": "hello",
            "device_id": device_id,
            "agent": "opensms-android",
            "protocol": 1,
        })
        self.status = "online"

        threading.Thread(
            target=self._heartbeat_loop,
            args=(device_id, interval),
            daemon=True,
        ).start()

        while not self._stop.is_set():
            raw = self._ws.recv()
            if raw is None:
                raise ConnectionError("gateway_closed")
            message = json.loads(raw)
            if message.get("type") == "ping":
                self._send({"type": "pong", "timestamp": int(time.time())})

    def _run(self):
        backoff = 2.0
        while not self._stop.is_set():
            config = load_connector_config(self.config_dir)
            gateway_url = str(config.get("gateway_url", "")).strip()
            device_id = str(config.get("device_id", "")).strip()
            if not config.get("enabled") or not gateway_url or not device_id:
                self.status = "disabled"
                self._stop.wait(10)
                continue

            try:
                self._connect_once(config)
                backoff = 2.0
            except Exception as exc:
                self.status = f"offline:{type(exc).__name__}"
                if self._ws:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                self._ws = None
                delay = min(60.0, backoff) + random.uniform(0, 1.0)
                self._stop.wait(delay)
                backoff = min(60.0, backoff * 2)
