import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GatewaySettings:
    db_path: str
    api_token: str
    admin_token: str
    pairing_ttl_seconds: int = 300
    heartbeat_timeout_seconds: int = 60
    pairing_rate_limit_per_minute: int = 10
    message_rate_limit_per_minute: int = 120

    @classmethod
    def from_env(cls) -> "GatewaySettings":
        api_token = os.environ.get("OPENSMS_API_TOKEN", "").strip()
        admin_token = os.environ.get("OPENSMS_ADMIN_TOKEN", "").strip()
        if not api_token:
            raise ValueError("OPENSMS_API_TOKEN is required")
        if not admin_token:
            raise ValueError("OPENSMS_ADMIN_TOKEN is required")
        try:
            pairing_ttl = int(os.environ.get("OPENSMS_PAIRING_TTL_SECONDS", "300"))
        except ValueError as exc:
            raise ValueError("OPENSMS_PAIRING_TTL_SECONDS must be an integer") from exc
        try:
            heartbeat_timeout = int(os.environ.get("OPENSMS_HEARTBEAT_TIMEOUT_SECONDS", "60"))
        except ValueError as exc:
            raise ValueError("OPENSMS_HEARTBEAT_TIMEOUT_SECONDS must be an integer") from exc
        if pairing_ttl < 30:
            raise ValueError("OPENSMS_PAIRING_TTL_SECONDS must be >= 30")
        if heartbeat_timeout < 20:
            raise ValueError("OPENSMS_HEARTBEAT_TIMEOUT_SECONDS must be >= 20")
        try:
            pairing_rate = int(os.environ.get("OPENSMS_PAIRING_RATE_LIMIT_PER_MINUTE", "10"))
            message_rate = int(os.environ.get("OPENSMS_MESSAGE_RATE_LIMIT_PER_MINUTE", "120"))
        except ValueError as exc:
            raise ValueError("rate limits must be integers") from exc
        if pairing_rate < 1 or message_rate < 1:
            raise ValueError("rate limits must be >= 1")
        return cls(
            db_path=os.environ.get("OPENSMS_DB_PATH", "./data/opensms-gateway.sqlite3"),
            api_token=api_token,
            admin_token=admin_token,
            pairing_ttl_seconds=pairing_ttl,
            heartbeat_timeout_seconds=heartbeat_timeout,
            pairing_rate_limit_per_minute=pairing_rate,
            message_rate_limit_per_minute=message_rate,
        )
