import json
import os
import random
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlparse, urlunparse

import websocket

from services.connectorConfig import load_connector_config
from services.jobLedger import JobLedger


MAX_NUMBER_CHARS = 64
MAX_TEXT_CHARS = 4000
PROTOCOL_VERSION = 1


class RemoteConnector:
    """Outbound-only OpenSMS connector owned by the Android background service."""

    def __init__(self, config_dir: str, sms_sender: Optional[Callable[[str, str], bool]] = None):
        self.config_dir = config_dir
        if sms_sender is None:
            from services.smsApi import send_sms
            sms_sender = send_sms
        self.sms_sender = sms_sender
        self.ledger = JobLedger(os.path.join(config_dir, "remote-jobs.json"))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws = None
        self._authenticated = False
        self.status = "stopped"

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._authenticated = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self.status = "stopped"

    def _send(self, payload: dict):
        self._ws.send(json.dumps(payload, separators=(",", ":")))

    def _config(self) -> dict:
        return load_connector_config(self.config_dir)

    def _device_ws_url(self, gateway_url: str) -> str:
        raw = gateway_url.strip().rstrip("/")
        parsed = urlparse(raw)
        if parsed.scheme in {"ws", "wss"}:
            if parsed.path and parsed.path != "/":
                return raw
            return raw + "/api/v1/device/connect"
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("unsupported_gateway_scheme")
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = parsed.path.rstrip("/") + "/api/v1/device/connect"
        return urlunparse((scheme, parsed.netloc, path, "", "", ""))

    def _send_hello(self):
        config = self._config()
        self._send({
            "type": "hello",
            "protocol": PROTOCOL_VERSION,
            "device_id": str(config.get("device_id", "")),
            "credential": str(config.get("device_credential", "")),
            "agent": "opensms-android",
        })

    def _heartbeat_loop(self, device_id: str, interval: int):
        while not self._stop.wait(interval):
            if not self._authenticated:
                continue
            try:
                self._send({
                    "type": "heartbeat",
                    "device_id": device_id,
                    "timestamp": int(time.time()),
                })
            except Exception:
                return

    def _device_id(self) -> str:
        return str(self._config().get("device_id", "")).strip()

    def _job_result(self, job_id: str, state: str, error: Optional[str] = None) -> dict:
        return {
            "type": "job_result",
            "job_id": job_id,
            "device_id": self._device_id(),
            "state": state,
            "ok": state == "sent",
            "error": error,
        }

    def _validate_job(self, message: dict) -> bool:
        job_id = message.get("job_id")
        number = message.get("number")
        text = message.get("text")
        return bool(
            isinstance(job_id, str) and job_id.strip()
            and isinstance(number, str) and 1 <= len(number) <= MAX_NUMBER_CHARS
            and isinstance(text, str) and 1 <= len(text) <= MAX_TEXT_CHARS
        )

    def _handle_job(self, message: dict):
        job_id = str(message.get("job_id", ""))
        if not self._authenticated:
            self._send(self._job_result(job_id, "failed", "not_authenticated"))
            return
        if message.get("command") != "send_sms":
            self._send(self._job_result(job_id, "failed", "unsupported_command"))
            return
        if not self._validate_job(message):
            self._send(self._job_result(job_id, "failed", "invalid_payload"))
            return

        prior = self.ledger.get(job_id)
        if prior:
            state = prior.get("state")
            if state in {"sent", "failed"} and isinstance(prior.get("result"), dict):
                self._send(dict(prior["result"]))
                return
            if state in {"accepted", "sending", "ambiguous"}:
                self.ledger.mark(job_id, "ambiguous")
                self._send(self._job_result(job_id, "failed", "duplicate_suppressed_uncertain"))
                return

        self.ledger.mark(job_id, "accepted")
        self._send({"type": "job_ack", "job_id": job_id, "device_id": self._device_id()})
        self.ledger.mark(job_id, "sending")

        try:
            ok = bool(self.sms_sender(message["number"], message["text"]))
            if ok:
                result = self._job_result(job_id, "sent", None)
                self.ledger.mark(job_id, "sent", result)
            else:
                result = self._job_result(job_id, "failed", "sms_send_failed")
                self.ledger.mark(job_id, "failed", result)
        except Exception:
            result = self._job_result(job_id, "failed", "sms_exception")
            self.ledger.mark(job_id, "failed", result)
        self.ledger.prune(500)
        self._send(result)

    def _process_message(self, message: dict) -> bool:
        msg_type = message.get("type")
        if msg_type == "hello_ok":
            self._authenticated = True
            self.status = "online"
        elif msg_type == "hello_error":
            self._authenticated = False
            self.status = "auth_failed"
            raise ConnectionError("gateway_auth_failed")
        elif msg_type == "ping":
            self._send({"type": "pong", "timestamp": int(time.time())})
        elif msg_type == "job":
            self._handle_job(message)
        return True

    def _process_raw(self, raw: str) -> bool:
        try:
            message = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(message, dict):
            return False
        return self._process_message(message)

    def _connect_once(self, config: dict):
        gateway_url = self._device_ws_url(str(config.get("gateway_url", "")))
        device_id = str(config.get("device_id", "")).strip()
        interval = max(10, int(config.get("heartbeat_seconds", 20)))

        self.status = "connecting"
        self._authenticated = False
        self._ws = websocket.create_connection(gateway_url, timeout=30)
        self._send_hello()
        self.status = "authenticating"

        threading.Thread(
            target=self._heartbeat_loop,
            args=(device_id, interval),
            daemon=True,
        ).start()

        while not self._stop.is_set():
            raw = self._ws.recv()
            if raw is None:
                raise ConnectionError("gateway_closed")
            self._process_raw(raw)

    def _run(self):
        backoff = 2.0
        while not self._stop.is_set():
            config = self._config()
            gateway_url = str(config.get("gateway_url", "")).strip()
            device_id = str(config.get("device_id", "")).strip()
            credential = str(config.get("device_credential", "")).strip()
            if not config.get("enabled") or not gateway_url or not device_id or not credential:
                self.status = "disabled"
                self._stop.wait(10)
                continue

            try:
                self._connect_once(config)
                backoff = 2.0
            except Exception as exc:
                self._authenticated = False
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
