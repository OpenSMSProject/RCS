import json
import os


DEFAULT_CONNECTOR_CONFIG = {
    "enabled": False,
    "gateway_url": "",
    "device_id": "",
    "heartbeat_seconds": 20,
}


def get_connector_config_path(config_dir: str) -> str:
    return os.path.join(config_dir, "connector.json")


def load_connector_config(config_dir: str) -> dict:
    path = get_connector_config_path(config_dir)
    config = dict(DEFAULT_CONNECTOR_CONFIG)
    if not os.path.exists(path):
        return config
    try:
        with open(path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, dict):
            config.update(saved)
    except Exception as exc:
        print(f"Could not load connector config: {exc}")
    config["heartbeat_seconds"] = max(10, int(config.get("heartbeat_seconds", 20)))
    return config


def save_connector_config(config_dir: str, config: dict) -> None:
    path = get_connector_config_path(config_dir)
    data = dict(DEFAULT_CONNECTOR_CONFIG)
    data.update(config)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
