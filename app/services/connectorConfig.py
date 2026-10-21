import json
import os
import secrets


DEFAULT_CONNECTOR_CONFIG = {
    "enabled": False,
    "gateway_url": "",
    "device_id": "",
    "device_name": "",
    "device_credential": "",
    "heartbeat_seconds": 20,
}


def get_connector_config_path(config_dir: str) -> str:
    return os.path.join(config_dir, "connector.json")


def ensure_device_id(config: dict) -> dict:
    data = dict(DEFAULT_CONNECTOR_CONFIG)
    if isinstance(config, dict):
        data.update(config)
    if not str(data.get("device_id", "")).strip():
        data["device_id"] = f"osms-{secrets.token_hex(6)}"
    return data


def _normalize(config: dict) -> dict:
    data = dict(DEFAULT_CONNECTOR_CONFIG)
    if isinstance(config, dict):
        data.update(config)
    data["enabled"] = bool(data.get("enabled", False))
    data["gateway_url"] = str(data.get("gateway_url", "")).strip().rstrip("/")
    data["device_id"] = str(data.get("device_id", "")).strip()
    data["device_name"] = str(data.get("device_name", "")).strip()
    data["device_credential"] = str(data.get("device_credential", "")).strip()
    try:
        heartbeat = int(data.get("heartbeat_seconds", 20))
    except (TypeError, ValueError):
        heartbeat = 20
    data["heartbeat_seconds"] = max(10, heartbeat)
    return data


def load_connector_config(config_dir: str) -> dict:
    path = get_connector_config_path(config_dir)
    if not os.path.exists(path):
        return dict(DEFAULT_CONNECTOR_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        return _normalize(saved if isinstance(saved, dict) else {})
    except Exception as exc:
        print(f"Could not load connector config: {type(exc).__name__}")
        return dict(DEFAULT_CONNECTOR_CONFIG)


def save_connector_config(config_dir: str, config: dict) -> None:
    os.makedirs(config_dir, exist_ok=True)
    path = get_connector_config_path(config_dir)
    data = _normalize(config)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
