import os
from dataclasses import dataclass
from typing import Optional


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class SaaSSettings:
    enabled: bool = False
    database_url: Optional[str] = None
    session_secret: Optional[str] = None

    @classmethod
    def from_env(cls) -> "SaaSSettings":
        raw_enabled = os.environ.get("OPENSMS_SAAS_ENABLED", "0").strip().lower()
        if raw_enabled in _TRUE:
            enabled = True
        elif raw_enabled in _FALSE:
            enabled = False
        else:
            raise ValueError("OPENSMS_SAAS_ENABLED must be a boolean")

        database_url = os.environ.get("OPENSMS_SAAS_DATABASE_URL", "").strip() or None
        session_secret = os.environ.get("OPENSMS_SAAS_SESSION_SECRET", "").strip() or None

        if not enabled:
            return cls(enabled=False, database_url=None, session_secret=None)
        if not database_url:
            raise ValueError("OPENSMS_SAAS_DATABASE_URL is required when SaaS is enabled")
        if not session_secret or len(session_secret) < 32:
            raise ValueError("SaaS session secret must be at least 32 characters")
        return cls(enabled=True, database_url=database_url, session_secret=session_secret)
