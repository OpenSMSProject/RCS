import asyncio
import os
import secrets
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status

from .config import GatewaySettings
from .models import MessageAccepted, MessageRequest, MessageStatus, PairDeviceRequest, PairDeviceResponse
from .registry import ConnectionRegistry
from .rate_limit import SlidingWindowRateLimiter
from .security import new_secret
from .storage import GatewayStore


SAFE_DEVICE_ERRORS = {
    "invalid_payload", "unsupported_command", "sms_send_failed", "permission_denied",
    "device_not_ready", "duplicate_suppressed_uncertain", "sms_exception",
}


def _bearer_value(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    return parts[1]


def _message_status(record: dict) -> dict:
    return {
        "message_id": record["message_id"], "device_id": record["device_id"], "to": record["to_number"],
        "state": record["state"], "created_at": record["created_at"], "updated_at": record["updated_at"],
        "acknowledged_at": record["acknowledged_at"], "completed_at": record["completed_at"],
        "error_code": record["error_code"], "dispatch_attempts": record["dispatch_attempts"],
    }


def _job_frame(record: dict) -> dict:
    return {"type": "job", "job_id": record["message_id"], "command": "send_sms", "number": record["to_number"], "text": record["text"]}


def create_app(settings: Optional[GatewaySettings] = None, store: Optional[GatewayStore] = None, registry: Optional[ConnectionRegistry] = None) -> FastAPI:
    settings = settings or GatewaySettings.from_env()
    store = store or GatewayStore(settings.db_path)
    registry = registry or ConnectionRegistry()
    pairing_limiter = SlidingWindowRateLimiter(settings.pairing_rate_limit_per_minute)
    message_limiter = SlidingWindowRateLimiter(settings.message_rate_limit_per_minute)
    app = FastAPI(title="OpenSMS Remote Gateway", version="1.0")
    app.state.settings = settings
    app.state.store = store
    app.state.registry = registry
    app.state.saas_enabled = False
    app.state.saas_engine = None

    from .saas.config import SaaSSettings

    saas_settings = SaaSSettings.from_env()
    if saas_settings.enabled:
        from .saas.db import create_engine_from_settings, session_factory
        from .saas.routes import build_saas_router

        saas_engine = create_engine_from_settings(saas_settings)
        saas_factory = session_factory(saas_engine)
        secure_cookies = os.environ.get("OPENSMS_SAAS_SECURE_COOKIES", "1").strip().lower() not in {"0", "false", "no", "off"}
        app.include_router(
            build_saas_router(saas_factory, store, secure_cookies=secure_cookies),
            prefix="/saas/v1",
        )
        app.state.saas_enabled = True
        app.state.saas_engine = saas_engine

    def require_admin(authorization: Optional[str] = Header(default=None)) -> None:
        token = _bearer_value(authorization)
        if token is None:
            raise HTTPException(status_code=401, detail="missing bearer token")
        if not secrets.compare_digest(token, settings.admin_token):
            raise HTTPException(status_code=403, detail="forbidden")

    def require_api(authorization: Optional[str] = Header(default=None)) -> None:
        token = _bearer_value(authorization)
        if token is None:
            raise HTTPException(status_code=401, detail="missing bearer token")
        if not secrets.compare_digest(token, settings.api_token):
            raise HTTPException(status_code=403, detail="forbidden")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        if not store.ready():
            raise HTTPException(status_code=503, detail="storage unavailable")
        if app.state.saas_enabled:
            from .saas.db import database_ready

            if not database_ready(app.state.saas_engine):
                raise HTTPException(status_code=503, detail="saas storage unavailable")
        return {"status": "ready"}

    @app.post("/api/v1/pairing-codes", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
    def create_pairing_code():
        code = f"{secrets.randbelow(1_000_000):06d}"
        record = store.create_pairing_code(code, ttl_seconds=settings.pairing_ttl_seconds)
        return {"pairing_code": code, "expires_at": record["expires_at"], "expires_in": settings.pairing_ttl_seconds}

    @app.post("/api/v1/devices/pair", response_model=PairDeviceResponse, status_code=status.HTTP_201_CREATED)
    def pair_device(payload: PairDeviceRequest, request: Request):
        client_key = request.client.host if request.client else "unknown"
        if not pairing_limiter.allow(client_key):
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        credential = new_secret("osmsdev")
        try:
            paired = store.pair_device(payload.pairing_code, payload.device_id, payload.name, credential)
        except ValueError as exc:
            if str(exc) == "device_exists":
                raise HTTPException(status_code=409, detail="device already exists")
            raise HTTPException(status_code=409, detail="device could not be paired")
        if not paired:
            raise HTTPException(status_code=400, detail="invalid or expired pairing code")
        return PairDeviceResponse(device_id=payload.device_id, device_credential=credential)

    @app.get("/api/v1/devices", dependencies=[Depends(require_admin)])
    def list_devices():
        return {"devices": store.list_devices()}

    @app.delete("/api/v1/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
    async def revoke_device(device_id: str):
        device = store.get_device(device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="device not found")
        store.revoke_device(device_id)
        await registry.disconnect(device_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def dispatch_record(record: dict) -> dict:
        device_id = record["device_id"]
        if not await registry.is_online(device_id):
            if record["state"] in {"queued", "dispatching"}:
                record = store.transition_message(record["message_id"], "waiting_device")
            return record
        record = store.transition_message(record["message_id"], "dispatching")
        if not await registry.enqueue(device_id, _job_frame(record)):
            record = store.transition_message(record["message_id"], "waiting_device")
        return record

    @app.post("/api/v1/messages", response_model=MessageAccepted, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_api)])
    async def submit_message(payload: MessageRequest, idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
        if not message_limiter.allow("api"):
            raise HTTPException(status_code=429, detail="rate limit exceeded")
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip()
            if not idempotency_key or len(idempotency_key) > 128:
                raise HTTPException(status_code=422, detail="invalid idempotency key")
            existing = store.get_message_by_idempotency(idempotency_key)
            if existing is not None:
                return MessageAccepted(message_id=existing["message_id"], state=existing["state"])
        device = store.get_device(payload.device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="device not found")
        if not device["enabled"]:
            raise HTTPException(status_code=409, detail="device disabled")
        record = store.create_message(payload.device_id, payload.to_number, payload.text, idempotency_key=idempotency_key)
        record = await dispatch_record(record)
        return MessageAccepted(message_id=record["message_id"], state=record["state"])

    @app.get("/api/v1/messages/{message_id}", response_model=MessageStatus, dependencies=[Depends(require_api)])
    def message_status(message_id: str):
        record = store.get_message(message_id)
        if record is None:
            raise HTTPException(status_code=404, detail="message not found")
        return _message_status(record)

    @app.websocket("/api/v1/device/connect")
    async def device_connect(websocket: WebSocket):
        await websocket.accept()
        device_id: Optional[str] = None
        authenticated = False
        try:
            try:
                hello = await asyncio.wait_for(websocket.receive_json(), timeout=settings.heartbeat_timeout_seconds)
            except Exception:
                await websocket.send_json({"type": "hello_error", "error": "invalid_hello"})
                await websocket.close(code=1008)
                return
            if not isinstance(hello, dict) or hello.get("type") != "hello" or hello.get("protocol") != 1:
                await websocket.send_json({"type": "hello_error", "error": "invalid_hello"})
                await websocket.close(code=1008)
                return
            device_id = str(hello.get("device_id", ""))
            credential = str(hello.get("credential", ""))
            if not store.verify_device_credential(device_id, credential):
                await websocket.send_json({"type": "hello_error", "error": "authentication_failed"})
                await websocket.close(code=1008)
                return
            authenticated = True
            await registry.register(device_id, websocket)
            store.set_device_online(device_id, True)
            await websocket.send_json({"type": "hello_ok", "protocol": 1, "device_id": device_id})
            for record in store.list_dispatchable(device_id):
                try:
                    record = store.transition_message(record["message_id"], "dispatching")
                except ValueError:
                    continue
                sent = await registry.enqueue(device_id, _job_frame(record))
                if not sent:
                    try:
                        store.transition_message(record["message_id"], "waiting_device")
                    except ValueError:
                        pass
                    break
            while True:
                frame = await asyncio.wait_for(websocket.receive_json(), timeout=settings.heartbeat_timeout_seconds)
                if not isinstance(frame, dict):
                    continue
                frame_type = frame.get("type")
                frame_device = frame.get("device_id")
                if frame_type in {"heartbeat", "job_ack", "job_result"} and frame_device != device_id:
                    continue
                if frame_type in {"heartbeat", "pong"}:
                    store.touch_device(device_id)
                elif frame_type == "job_ack":
                    job_id = str(frame.get("job_id", ""))
                    message = store.get_message(job_id)
                    if message and message["device_id"] == device_id and message["state"] not in {"sent", "failed"}:
                        try:
                            store.transition_message(job_id, "acknowledged")
                        except ValueError:
                            pass
                elif frame_type == "job_result":
                    job_id = str(frame.get("job_id", ""))
                    message = store.get_message(job_id)
                    if not message or message["device_id"] != device_id or message["state"] in {"sent", "failed"}:
                        continue
                    ok = frame.get("ok") is True or frame.get("state") == "sent"
                    if ok:
                        try:
                            store.transition_message(job_id, "sent", error_code=None)
                        except ValueError:
                            pass
                    else:
                        raw_error = frame.get("error")
                        error_code = raw_error if raw_error in SAFE_DEVICE_ERRORS else "device_error"
                        try:
                            store.transition_message(job_id, "failed", error_code=error_code)
                        except ValueError:
                            pass
        except asyncio.TimeoutError:
            try:
                await websocket.close(code=1001)
            except Exception:
                pass
        except WebSocketDisconnect:
            pass
        finally:
            if authenticated and device_id:
                await registry.unregister(device_id, websocket)
                if not await registry.is_online(device_id):
                    store.set_device_online(device_id, False)
    return app
