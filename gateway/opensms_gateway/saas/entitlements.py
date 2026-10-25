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


def _active_plan(session: Session, tenant: Tenant) -> Optional[Plan]:
    entitlement = session.scalar(
        select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant.id)
    )
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

    plan = _active_plan(session, tenant)
    if plan is not None:
        if capability == "users":
            return _limit_decision(session, tenant_id, capability, plan.max_users)
        if capability == "devices":
            return _limit_decision(session, tenant_id, capability, plan.max_devices)
        if capability == "api_keys":
            return _limit_decision(session, tenant_id, capability, plan.max_api_keys)
        if capability == "external_api":
            return EntitlementDecision(bool(plan.external_api), None if plan.external_api else "not_entitled", None, None)
        return EntitlementDecision(bool(plan.bulk_campaigns), None if plan.bulk_campaigns else "not_entitled", None, None)

    trial = _active_trial(session, tenant_id)
    if trial is None:
        return EntitlementDecision(False, "not_entitled", None, None)
    if _aware(now) >= _aware(trial.expires_at):
        return EntitlementDecision(False, "trial_expired", None, None)

    if capability == "users":
        return _limit_decision(session, tenant_id, capability, trial.max_users)
    if capability == "devices":
        return _limit_decision(session, tenant_id, capability, trial.max_devices)
    if capability == "api_keys":
        return _limit_decision(session, tenant_id, capability, trial.max_api_keys)
    if capability == "external_api":
        return EntitlementDecision(bool(trial.external_api), None if trial.external_api else "not_entitled", None, None)
    return EntitlementDecision(bool(trial.bulk_campaigns), None if trial.bulk_campaigns else "not_entitled", None, None)
