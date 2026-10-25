from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from .auth import Principal
from .models import AuditEvent


_SENSITIVE_FRAGMENTS = (
    "password", "token", "secret", "credential", "message", "body", "text", "content",
)


def _redact(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def record_audit(
    session: Session,
    *,
    actor: Principal,
    tenant_id: Optional[UUID],
    action: str,
    target_type: str,
    target_id: Optional[str],
    details: Optional[dict] = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor.user_id,
        tenant_id=tenant_id,
        action=str(action),
        target_type=str(target_type),
        target_id=target_id,
        details=_redact(details or {}),
    )
    session.add(event)
    session.commit()
    return event
