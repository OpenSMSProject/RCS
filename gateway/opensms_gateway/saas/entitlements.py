from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from .auth import Principal
from .models import ApiKey, Membership, Plan, Tenant, TenantDevice, TenantEntitlement, Trial


@dataclass(frozen=True)
class EntitlementDecision:
    allowed: bool
    reason: Optional[str] = None
    limit: Optional[int] = None
    used: Optional[int] = None


TRIAL_LIMITS = {
    "users": 2,
    "devices": 1,
    "api_keys": 1,
    "messages": 200,
    "external_api": True,
    "bulk_campaigns": False,
}


def _trial_active(trial: Optional[Trial], now: datetime) -> bool:
    if trial is None:
        return False
    end = trial.ends_at
    if end.tzinfo is None and now.tzinfo is not None:
        end = end.replace(tzinfo=timezone.utc)
    return now < end


def _count_used(session, tenant_id: UUID, capability: str) -> Optional[int]:
    if capability == "users":
        return int(session.scalar(select(func.count(Membership.id)).where(Membership.tenant_id == tenant_id)) or 0)
    if capability == "devices":
        return int(session.scalar(select(func.count(TenantDevice.id)).where(TenantDevice.tenant_id == tenant_id)) or 0)
    if capability == "api_keys":
        return int(session.scalar(select(func.count(ApiKey.id)).where(ApiKey.tenant_id == tenant_id, ApiKey.revoked_at.is_(None))) or 0)
    return None


def evaluate_entitlement(session, *, tenant_id: UUID, capability: str, now: datetime) -> EntitlementDecision:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        return EntitlementDecision(False, "tenant_not_found")

    override = session.scalar(
        select(TenantEntitlement).where(
            TenantEntitlement.tenant_id == tenant_id,
            TenantEntitlement.capability == capability,
        )
    )
    if override is not None:
        if override.expires_at is None or now < override.expires_at:
            if override.bool_value is not None:
                return EntitlementDecision(bool(override.bool_value), None if override.bool_value else "disabled")
            if override.int_value is not None:
                used = _count_used(session, tenant_id, capability)
                allowed = used is None or used < override.int_value
                return EntitlementDecision(allowed, None if allowed else "limit_reached", override.int_value, used)

    if tenant.plan_id is not None:
        plan = session.get(Plan, tenant.plan_id)
        if plan is not None and plan.active:
            mapping = {
                "users": plan.included_users,
                "devices": plan.included_devices,
                "api_keys": plan.included_api_keys,
                "messages": plan.included_messages,
                "external_api": plan.external_api_enabled,
                "bulk_campaigns": plan.bulk_campaigns_enabled,
            }
            value = mapping.get(capability)
            if isinstance(value, bool):
                return EntitlementDecision(value, None if value else "disabled")
            if isinstance(value, int):
                used = _count_used(session, tenant_id, capability)
                allowed = used is None or used < value
                return EntitlementDecision(allowed, None if allowed else "limit_reached", value, used)

    trial = session.scalar(select(Trial).where(Trial.tenant_id == tenant_id))
    if not _trial_active(trial, now):
        return EntitlementDecision(False, "trial_expired")
    if capability not in TRIAL_LIMITS:
        return EntitlementDecision(False, "not_entitled")
    value = TRIAL_LIMITS[capability]
    if isinstance(value, bool):
        return EntitlementDecision(value, None if value else "disabled")
    used = _count_used(session, tenant_id, capability)
    allowed = used is None or used < value
    return EntitlementDecision(allowed, None if allowed else "limit_reached", value, used)


def assign_plan(session, *, tenant_id: UUID, plan_id: UUID) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    plan = session.get(Plan, plan_id)
    if tenant is None or plan is None:
        raise ValueError("tenant or plan not found")
    if tenant.tenant_type != plan.tenant_type:
        raise ValueError("plan tenant type does not match tenant type")
    tenant.plan_id = plan.id
    session.commit()
    return tenant


def extend_trial(session, *, tenant_id: UUID, days: int, actor: Principal, now: Optional[datetime] = None) -> Trial:
    if not actor.is_super_admin:
        raise PermissionError("Super Admin required")
    if days <= 0:
        raise ValueError("days must be positive")
    trial = session.scalar(select(Trial).where(Trial.tenant_id == tenant_id))
    if trial is None:
        raise ValueError("trial not found")
    now = now or datetime.now(timezone.utc)
    trial.ends_at = trial.ends_at + timedelta(days=days)
    trial.extended_at = now
    session.commit()
    return trial
