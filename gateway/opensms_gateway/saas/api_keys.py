import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select

from .auth import Principal
from .entitlements import evaluate_entitlement
from .models import ApiKey, AuditEvent, Tenant, TenantRole, TenantStatus


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _require_key_manager(actor: Principal, tenant_id: UUID) -> None:
    if actor.tenant_id != tenant_id or actor.tenant_status != TenantStatus.active:
        raise PermissionError("forbidden")
    if actor.role not in {TenantRole.Owner, TenantRole.Admin}:
        raise PermissionError("forbidden")


def _audit_key(session, *, actor: Principal, record: ApiKey, action: str) -> None:
    session.add(
        AuditEvent(
            actor_user_id=actor.user_id,
            tenant_id=record.tenant_id,
            action=action,
            target_type="api_key",
            target_id=str(record.id),
            metadata_json={"label": record.label},
        )
    )
    session.commit()


def create_api_key(session, *, tenant_id: UUID, actor: Principal, label: str) -> tuple[ApiKey, str]:
    _require_key_manager(actor, tenant_id)
    clean_label = (label or "").strip()
    if not clean_label:
        raise ValueError("label is required")
    decision = evaluate_entitlement(session, tenant_id=tenant_id, capability="api_keys", now=datetime.now(timezone.utc))
    if not decision.allowed:
        raise ValueError(f"API key limit reached: {decision.reason}")
    raw_key = "osms_live_" + secrets.token_urlsafe(32)
    record = ApiKey(tenant_id=tenant_id, label=clean_label, key_hash=_hash_api_key(raw_key))
    session.add(record)
    session.commit()
    session.refresh(record)
    _audit_key(session, actor=actor, record=record, action="api_key.create")
    return record, raw_key


def authenticate_api_key(session, raw_key: str) -> Optional[Principal]:
    if not raw_key or not raw_key.startswith("osms_live_"):
        return None
    record = session.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == _hash_api_key(raw_key),
            ApiKey.revoked_at.is_(None),
        )
    )
    if record is None:
        return None
    tenant = session.get(Tenant, record.tenant_id)
    if tenant is None or tenant.status != TenantStatus.active:
        return None
    record.last_used_at = datetime.now(timezone.utc)
    session.commit()
    return Principal(UUID(int=0), tenant.id, TenantRole.Operator, False, tenant.status)


def revoke_api_key(session, *, key_id: UUID, actor: Principal) -> None:
    record = session.get(ApiKey, key_id)
    if record is None:
        raise ValueError("API key not found")
    _require_key_manager(actor, record.tenant_id)
    record.revoked_at = datetime.now(timezone.utc)
    session.commit()
    _audit_key(session, actor=actor, record=record, action="api_key.revoke")
