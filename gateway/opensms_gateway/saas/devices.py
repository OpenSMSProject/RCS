from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal
from .entitlements import evaluate_entitlement
from .models import TenantDevice, TenantRole


def _require_tenant_actor(actor: Principal, tenant_id: UUID, *, manage: bool) -> None:
    if actor.is_super_admin or actor.tenant_id != tenant_id:
        raise PermissionError("tenant device access is not allowed")
    allowed = {TenantRole.Owner, TenantRole.Admin} if manage else {TenantRole.Owner, TenantRole.Admin, TenantRole.Operator}
    if actor.role not in allowed:
        raise PermissionError("tenant device access is not allowed")


def claim_existing_device(
    session: Session,
    *,
    tenant_id: UUID,
    device_id: str,
    actor: Principal,
    gateway_store,
) -> TenantDevice:
    _require_tenant_actor(actor, tenant_id, manage=True)
    clean_device_id = str(device_id or "").strip()
    if not clean_device_id:
        raise LookupError("device not available")

    existing = session.scalar(select(TenantDevice).where(TenantDevice.device_id == clean_device_id))
    if existing is not None:
        raise LookupError("device not available")

    legacy = gateway_store.get_device(clean_device_id)
    if legacy is None or not legacy.get("enabled", False):
        raise LookupError("device not available")

    decision = evaluate_entitlement(
        session,
        tenant_id=tenant_id,
        capability="devices",
        now=datetime.now(timezone.utc),
    )
    if not decision.allowed:
        if decision.reason == "limit_reached":
            raise PermissionError("device limit reached")
        raise PermissionError(f"device claim denied: {decision.reason}")

    mapping = TenantDevice(tenant_id=tenant_id, device_id=clean_device_id)
    session.add(mapping)
    session.commit()
    return mapping


def list_tenant_devices(
    session: Session,
    *,
    tenant_id: UUID,
    actor: Principal,
) -> list[TenantDevice]:
    _require_tenant_actor(actor, tenant_id, manage=False)
    return list(
        session.scalars(
            select(TenantDevice)
            .where(TenantDevice.tenant_id == tenant_id)
            .order_by(TenantDevice.claimed_at, TenantDevice.device_id)
        ).all()
    )


def release_device(
    session: Session,
    *,
    tenant_id: UUID,
    device_id: str,
    actor: Principal,
) -> None:
    _require_tenant_actor(actor, tenant_id, manage=True)
    mapping = session.scalar(
        select(TenantDevice).where(
            TenantDevice.tenant_id == tenant_id,
            TenantDevice.device_id == str(device_id or "").strip(),
        )
    )
    if mapping is None:
        raise LookupError("device not found")
    session.delete(mapping)
    session.commit()
