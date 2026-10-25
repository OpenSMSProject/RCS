from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    ApiKey,
    Membership,
    Plan,
    Tenant,
    TenantDevice,
    TenantEntitlement,
    TenantStatus,
    Trial,
)


@dataclass(frozen=True)
class EntitlementDecision:
    allowed: bool
    reason: Optional[str]
    limit: Optional[int]
    used: Optional[int]


_CAPABILITIES = frozenset({"users", "devices", "api_keys", "external_api", "bulk_campaigns"})
_LIMIT_CAPABILITIES = frozenset({"users", "devices", "api_keys"})
_BOOLEAN_CAPABILITIES = frozenset({"external_api", "bulk_campaigns"})


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def validate_plan_assignment(session: Session, *, tenant_id: UUID, plan_id: UUID) -> None:
    tenant = session.get(Tenant, tenant_id)
    plan = session.get(Plan, plan_id)
    if tenant is None:
        raise ValueError("tenant not found")
    if plan is None:
        raise ValueError("plan not found")
    if plan.tenant_type != tenant.tenant_type:
        raise ValueError("plan tenant type mismatch")


def _entitlement_record(session: Session, tenant_id: UUID) -> Optional[TenantEntitlement]:
    return session.scalar(
        select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id)
    )


def _active_plan(
    session: Session,
    tenant: Tenant,
    entitlement: Optional[TenantEntitlement],
) -> Optional[Plan]:
    if entitlement is None or entitlement.plan_id is None:
        return None
    plan = session.get(Plan, entitlement.plan_id)
    if plan is None or not plan.active:
        return None
    if plan.tenant_type != tenant.tenant_type:
        raise ValueError("plan tenant type mismatch")
    return plan


def _active_trial(session: Session, tenant_id: UUID) -> Optional[Trial]:
    return session.scalar(select(Trial).where(Trial.tenant_id == tenant_id))


def _usage_count(session: Session, tenant_id: UUID, capability: str) -> int:
    if capability == "users":
        stmt = select(func.count()).select_from(Membership).where(Membership.tenant_id == tenant_id)
    elif capability == "devices":
        stmt = select(func.count()).select_from(TenantDevice).where(TenantDevice.tenant_id == tenant_id)
    elif capability == "api_keys":
        stmt = select(func.count()).select_from(ApiKey).where(
            ApiKey.tenant_id == tenant_id,
            ApiKey.revoked_at.is_(None),
        )
    else:
        raise ValueError(f"capability {capability!r} does not have a usage counter")
    return int(session.scalar(stmt) or 0)


def _limit_decision(session: Session, tenant_id: UUID, capability: str, limit: int) -> EntitlementDecision:
    used = _usage_count(session, tenant_id, capability)
    if used >= int(limit):
        return EntitlementDecision(False, "limit_reached", int(limit), used)
    return EntitlementDecision(True, None, int(limit), used)


def _limit_with_override(
    entitlement: Optional[TenantEntitlement],
    capability: str,
    default: int,
) -> int:
    if entitlement is None:
        return int(default)
    value = (entitlement.courtesy_overrides or {}).get(capability)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return int(default)
    return value


def _boolean_with_override(
    entitlement: Optional[TenantEntitlement],
    capability: str,
    default: bool,
) -> bool:
    if entitlement is None:
        return bool(default)
    value = (entitlement.courtesy_overrides or {}).get(capability)
    return value if isinstance(value, bool) else bool(default)


def _boolean_decision(value: bool) -> EntitlementDecision:
    return EntitlementDecision(value, None if value else "not_entitled", None, None)


def evaluate_entitlement(
    session: Session,
    *,
    tenant_id: UUID,
    capability: str,
    now: datetime,
) -> EntitlementDecision:
    if capability not in _CAPABILITIES:
        raise ValueError(f"unknown capability: {capability}")

    tenant = session.get(Tenant, tenant_id)
    if tenant is None or tenant.status != TenantStatus.active:
        return EntitlementDecision(False, "tenant_unavailable", None, None)

    entitlement = _entitlement_record(session, tenant_id)
    plan = _active_plan(session, tenant, entitlement)
    if plan is not None:
        if capability == "users":
            limit = _limit_with_override(entitlement, capability, plan.max_users)
            return _limit_decision(session, tenant_id, capability, limit)
        if capability == "devices":
            limit = _limit_with_override(entitlement, capability, plan.max_devices)
            return _limit_decision(session, tenant_id, capability, limit)
        if capability == "api_keys":
            limit = _limit_with_override(entitlement, capability, plan.max_api_keys)
            return _limit_decision(session, tenant_id, capability, limit)
        if capability == "external_api":
            return _boolean_decision(_boolean_with_override(entitlement, capability, plan.external_api))
        return _boolean_decision(_boolean_with_override(entitlement, capability, plan.bulk_campaigns))

    trial = _active_trial(session, tenant_id)
    if trial is None:
        return EntitlementDecision(False, "not_entitled", None, None)
    if _aware(now) >= _aware(trial.expires_at):
        return EntitlementDecision(False, "trial_expired", None, None)

    if capability == "users":
        limit = _limit_with_override(entitlement, capability, trial.max_users)
        return _limit_decision(session, tenant_id, capability, limit)
    if capability == "devices":
        limit = _limit_with_override(entitlement, capability, trial.max_devices)
        return _limit_decision(session, tenant_id, capability, limit)
    if capability == "api_keys":
        limit = _limit_with_override(entitlement, capability, trial.max_api_keys)
        return _limit_decision(session, tenant_id, capability, limit)
    if capability == "external_api":
        return _boolean_decision(_boolean_with_override(entitlement, capability, trial.external_api))
    return _boolean_decision(_boolean_with_override(entitlement, capability, trial.bulk_campaigns))
