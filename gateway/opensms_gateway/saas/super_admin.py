from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import record_audit
from .auth import Principal
from .entitlements import validate_plan_assignment
from .models import Tenant, TenantEntitlement, TenantStatus, Trial


_ALLOWED_OVERRIDES = {"users", "devices", "api_keys", "external_api", "bulk_campaigns", "messages"}


def _require_super_admin(actor: Principal) -> None:
    if not actor.is_super_admin:
        raise PermissionError("Super Admin required")


def _tenant(session: Session, tenant_id: UUID) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise LookupError("tenant not found")
    return tenant


def suspend_tenant(session: Session, *, tenant_id: UUID, actor: Principal) -> Tenant:
    _require_super_admin(actor)
    tenant = _tenant(session, tenant_id)
    tenant.status = TenantStatus.suspended
    record_audit(session, actor=actor, tenant_id=tenant.id, action="tenant.suspended", target_type="tenant", target_id=str(tenant.id))
    return tenant


def reactivate_tenant(session: Session, *, tenant_id: UUID, actor: Principal) -> Tenant:
    _require_super_admin(actor)
    tenant = _tenant(session, tenant_id)
    tenant.status = TenantStatus.active
    record_audit(session, actor=actor, tenant_id=tenant.id, action="tenant.reactivated", target_type="tenant", target_id=str(tenant.id))
    return tenant


def extend_trial(session: Session, *, tenant_id: UUID, actor: Principal, days: int) -> Trial:
    _require_super_admin(actor)
    if int(days) <= 0:
        raise ValueError("trial extension days must be positive")
    _tenant(session, tenant_id)
    trial = session.scalar(select(Trial).where(Trial.tenant_id == tenant_id))
    if trial is None:
        raise LookupError("trial not found")
    trial.expires_at = trial.expires_at + timedelta(days=int(days))
    trial.extended_by_user_id = actor.user_id
    record_audit(
        session,
        actor=actor,
        tenant_id=tenant_id,
        action="trial.extended",
        target_type="trial",
        target_id=str(trial.id),
        details={"days": int(days)},
    )
    return trial


def change_plan(session: Session, *, tenant_id: UUID, plan_id: UUID, actor: Principal) -> TenantEntitlement:
    _require_super_admin(actor)
    validate_plan_assignment(session, tenant_id=tenant_id, plan_id=plan_id)
    entitlement = session.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id))
    if entitlement is None:
        entitlement = TenantEntitlement(tenant_id=tenant_id, plan_id=plan_id)
        session.add(entitlement)
    else:
        entitlement.plan_id = plan_id
    session.flush()
    record_audit(
        session,
        actor=actor,
        tenant_id=tenant_id,
        action="tenant.plan_changed",
        target_type="tenant_entitlement",
        target_id=str(entitlement.id),
        details={"plan_id": str(plan_id)},
    )
    return entitlement


def set_courtesy_override(
    session: Session,
    *,
    tenant_id: UUID,
    actor: Principal,
    capability: str,
    value,
) -> TenantEntitlement:
    _require_super_admin(actor)
    _tenant(session, tenant_id)
    if capability not in _ALLOWED_OVERRIDES:
        raise ValueError("unsupported courtesy override capability")
    entitlement = session.scalar(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id))
    if entitlement is None:
        entitlement = TenantEntitlement(tenant_id=tenant_id, plan_id=None, courtesy_overrides={})
        session.add(entitlement)
        session.flush()
    overrides = dict(entitlement.courtesy_overrides or {})
    overrides[capability] = value
    entitlement.courtesy_overrides = overrides
    record_audit(
        session,
        actor=actor,
        tenant_id=tenant_id,
        action="tenant.courtesy_override",
        target_type="tenant_entitlement",
        target_id=str(entitlement.id),
        details={"capability": capability, "value": value},
    )
    return entitlement
