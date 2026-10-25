import hashlib
import secrets
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal
from .entitlements import evaluate_entitlement
from .models import ApiKey, AuditEvent, Tenant, TenantRole, TenantStatus


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _require_key_manager(actor: Principal, tenant_id: UUID) -> None:
    if actor.is_super_admin or actor.tenant_id != tenant_id or actor.role not in {TenantRole.Owner, TenantRole.Admin}:
        raise PermissionError("API key management is not allowed")


def create_api_key(
    session: Session,
    *,
    tenant_id: UUID,
    actor: Principal,
    label: str,
) -> tuple[ApiKey, str]:
    _require_key_manager(actor, tenant_id)
    decision = evaluate_entitlement(
        session,
        tenant_id=tenant_id,
        capability="api_keys",
        now=datetime.now(timezone.utc),
    )
    if not decision.allowed:
        if decision.reason == "limit_reached":
            raise PermissionError("API key limit reached")
        raise PermissionError(f"API key creation denied: {decision.reason}")
    clean_label = str(label or "").strip()
    if not clean_label or len(clean_label) > 120:
        raise ValueError("API key label is required and must be <= 120 characters")
    raw_key = "osms_live_" + secrets.token_urlsafe(32)
    record = ApiKey(
        tenant_id=tenant_id,
        created_by_user_id=actor.user_id,
        label=clean_label,
        key_hash=_hash_api_key(raw_key),
        key_prefix=raw_key[:20],
    )
    session.add(record)
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=actor.user_id,
            tenant_id=tenant_id,
            action="api_key.created",
            target_type="api_key",
            target_id=str(record.id),
            details={"label": clean_label, "key_prefix": record.key_prefix},
        )
    )
    session.commit()
    return record, raw_key


def authenticate_api_key(session: Session, raw_key: str) -> Principal:
    if not isinstance(raw_key, str) or not raw_key.startswith("osms_live_"):
        raise HTTPException(status_code=401, detail="invalid API key")
    key_hash = _hash_api_key(raw_key)
    record = session.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if record is None or record.revoked_at is not None:
        raise HTTPException(status_code=401, detail="invalid API key")
    tenant = session.get(Tenant, record.tenant_id)
    if tenant is None or tenant.status != TenantStatus.active:
        raise HTTPException(status_code=403, detail="tenant unavailable")
    record.last_used_at = datetime.now(timezone.utc)
    session.commit()
    return Principal(
        user_id=record.created_by_user_id,
        tenant_id=record.tenant_id,
        role=TenantRole.Operator,
        is_super_admin=False,
    )


def revoke_api_key(session: Session, *, key_id: UUID, actor: Principal) -> None:
    if actor.is_super_admin or actor.tenant_id is None or actor.role not in {TenantRole.Owner, TenantRole.Admin}:
        raise PermissionError("API key management is not allowed")
    record = session.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == actor.tenant_id)
    )
    if record is None:
        raise LookupError("API key not found")
    if record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        session.add(
            AuditEvent(
                actor_user_id=actor.user_id,
                tenant_id=actor.tenant_id,
                action="api_key.revoked",
                target_type="api_key",
                target_id=str(record.id),
                details={"label": record.label, "key_prefix": record.key_prefix},
            )
        )
        session.commit()
