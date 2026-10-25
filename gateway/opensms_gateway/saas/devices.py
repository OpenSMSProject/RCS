from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from .auth import Principal
from .entitlements import evaluate_entitlement
from .models import TenantDevice, TenantRole, TenantStatus


def _require_device_manager(actor: Principal, tenant_id: UUID) -> None:
    if actor.tenant_id != tenant_id or actor.tenant_status != TenantStatus.active:
        raise PermissionError("forbidden")
    if actor.role not in {TenantRole.Owner, TenantRole.Admin}:
        raise PermissionError("forbidden")


def claim_legacy_device(session, *, tenant_id: UUID, device_id: str, actor: Principal, gateway_store) -> TenantDevice:
    _require_device_manager(actor, tenant_id)
    legacy = gateway_store.get_device(device_id)
    if legacy is None:
        raise ValueError("legacy device not found")
    existing = session.scalar(select(TenantDevice).where(TenantDevice.device_id == device_id))
    if existing is not None:
        if existing.tenant_id == tenant_id:
            return existing
        raise ValueError("device already claimed by another tenant")
    decision = evaluate_entitlement(session, tenant_id=tenant_id, capability="devices", now=datetime.now(timezone.utc))
    if not decision.allowed:
        raise ValueError(f"device limit reached: {decision.reason}")
    mapping = TenantDevice(tenant_id=tenant_id, device_id=device_id)
    session.add(mapping)
    session.commit()
    session.refresh(mapping)
    return mapping


def list_tenant_devices(session, *, tenant_id: UUID, gateway_store) -> list[dict]:
    mappings = session.scalars(
        select(TenantDevice).where(TenantDevice.tenant_id == tenant_id).order_by(TenantDevice.claimed_at, TenantDevice.device_id)
    ).all()
    result = []
    for mapping in mappings:
        legacy = gateway_store.get_device(mapping.device_id)
        if legacy is None:
            result.append({"device_id": mapping.device_id, "missing_legacy_device": True})
            continue
        safe = dict(legacy)
        safe.pop("credential_hash", None)
        safe["tenant_device_id"] = str(mapping.id)
        safe["claimed_at"] = mapping.claimed_at
        result.append(safe)
    return result
