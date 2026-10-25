from typing import Optional
from uuid import UUID

from sqlalchemy import select

from .auth import Principal
from .entitlements import assign_plan, extend_trial
from .models import AuditEvent, Tenant, TenantEntitlement, TenantStatus


_SENSITIVE_KEYS = {"credential", "credentials", "password", "secret", "token", "api_key", "message_body", "message", "text"}


def _safe_metadata(metadata: Optional[dict]) -> Optional[dict]:
    if metadata is None:
        return None
    return {key: value for key, value in metadata.items() if key.lower() not in _SENSITIVE_KEYS}


def record_audit(
    session,
    *,
    actor_user_id: Optional[UUID],
    tenant_id: Optional[UUID],
    action: str,
    target_type: str,
    target_id: Optional[str],
    metadata: Optional[dict] = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_json=_safe_metadata(metadata),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _require_super_admin(actor: Principal) -> None:
    if not actor.is_super_admin:
        raise PermissionError("Super Admin required")


def suspend_tenant(session, *, tenant_id: UUID, actor: Principal) -> Tenant:
    _require_super_admin(actor)
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("tenant not found")
    tenant.status = TenantStatus.suspended
    session.commit()
    record_audit(session, actor_user_id=actor.user_id, tenant_id=tenant.id, action="tenant.suspend", target_type="tenant", target_id=str(tenant.id))
    return tenant


def reactivate_tenant(session, *, tenant_id: UUID, actor: Principal) -> Tenant:
    _require_super_admin(actor)
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("tenant not found")
    tenant.status = TenantStatus.active
    session.commit()
    record_audit(session, actor_user_id=actor.user_id, tenant_id=tenant.id, action="tenant.reactivate", target_type="tenant", target_id=str(tenant.id))
    return tenant


def change_tenant_plan(session, *, tenant_id: UUID, plan_id: UUID, actor: Principal) -> Tenant:
    _require_super_admin(actor)
    tenant = assign_plan(session, tenant_id=tenant_id, plan_id=plan_id)
    record_audit(session, actor_user_id=actor.user_id, tenant_id=tenant.id, action="tenant.plan_change", target_type="plan", target_id=str(plan_id))
    return tenant


def extend_tenant_trial(session, *, tenant_id: UUID, days: int, actor: Principal):
    _require_super_admin(actor)
    trial = extend_trial(session, tenant_id=tenant_id, days=days, actor=actor)
    record_audit(session, actor_user_id=actor.user_id, tenant_id=tenant_id, action="tenant.trial_extend", target_type="trial", target_id=str(trial.id), metadata={"days": days})
    return trial


def courtesy_entitlement(
    session,
    *,
    tenant_id: UUID,
    capability: str,
    actor: Principal,
    int_value: Optional[int] = None,
    bool_value: Optional[bool] = None,
) -> TenantEntitlement:
    _require_super_admin(actor)
    if int_value is None and bool_value is None:
        raise ValueError("an entitlement value is required")
    record = session.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id, TenantEntitlement.capability == capability))
    if record is None:
        record = TenantEntitlement(tenant_id=tenant_id, capability=capability, source="courtesy")
        session.add(record)
    record.int_value = int_value
    record.bool_value = bool_value
    record.source = "courtesy"
    session.commit()
    session.refresh(record)
    record_audit(session, actor_user_id=actor.user_id, tenant_id=tenant_id, action="tenant.entitlement_override", target_type="entitlement", target_id=str(record.id), metadata={"capability": capability, "int_value": int_value, "bool_value": bool_value})
    return record
