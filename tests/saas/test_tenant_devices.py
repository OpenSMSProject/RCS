from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import pytest


def _session():
    from gateway.opensms_gateway.saas.models import Base
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _owner(session, email, doc):
    from gateway.opensms_gateway.saas.auth import Principal
    from gateway.opensms_gateway.saas.models import Membership, TenantRole, TenantStatus, TenantType
    from gateway.opensms_gateway.saas.tenants import provision_trial_tenant
    tenant = provision_trial_tenant(session, email=email, password="password", tenant_type=TenantType.PF, document_number=doc, display_name=email)
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    return tenant, Principal(membership.user_id, tenant.id, TenantRole.Owner, False, TenantStatus.active)


def test_claim_requires_existing_legacy_device_and_copies_no_credential():
    from gateway.opensms_gateway.saas.devices import claim_legacy_device
    from gateway.opensms_gateway.storage import GatewayStore

    store = GatewayStore(":memory:")
    store.create_device("device-1", "Phone", "secret-device-credential")
    with _session() as session:
        tenant, owner = _owner(session, "a@example.com", "111.222.333-44")
        mapping = claim_legacy_device(session, tenant_id=tenant.id, device_id="device-1", actor=owner, gateway_store=store)
        assert mapping.device_id == "device-1"
        assert "credential" not in {c.name for c in mapping.__table__.columns}
        with pytest.raises(ValueError, match="not found"):
            claim_legacy_device(session, tenant_id=tenant.id, device_id="missing", actor=owner, gateway_store=store)


def test_one_device_cannot_belong_to_two_tenants_and_trial_limit_is_enforced():
    from gateway.opensms_gateway.saas.devices import claim_legacy_device
    from gateway.opensms_gateway.storage import GatewayStore

    store = GatewayStore(":memory:")
    store.create_device("device-1", "One", "secret-1")
    store.create_device("device-2", "Two", "secret-2")
    with _session() as session:
        tenant_a, owner_a = _owner(session, "a@example.com", "111.222.333-44")
        tenant_b, owner_b = _owner(session, "b@example.com", "555.666.777-88")
        claim_legacy_device(session, tenant_id=tenant_a.id, device_id="device-1", actor=owner_a, gateway_store=store)
        with pytest.raises(ValueError, match="already claimed"):
            claim_legacy_device(session, tenant_id=tenant_b.id, device_id="device-1", actor=owner_b, gateway_store=store)
        with pytest.raises(ValueError, match="limit"):
            claim_legacy_device(session, tenant_id=tenant_a.id, device_id="device-2", actor=owner_a, gateway_store=store)


def test_list_combines_safe_legacy_state_only_for_requested_tenant():
    from gateway.opensms_gateway.saas.devices import claim_legacy_device, list_tenant_devices
    from gateway.opensms_gateway.storage import GatewayStore

    store = GatewayStore(":memory:")
    store.create_device("device-1", "One", "credential-one")
    store.create_device("device-2", "Two", "credential-two")
    with _session() as session:
        tenant_a, owner_a = _owner(session, "a@example.com", "111.222.333-44")
        tenant_b, owner_b = _owner(session, "b@example.com", "555.666.777-88")
        claim_legacy_device(session, tenant_id=tenant_a.id, device_id="device-1", actor=owner_a, gateway_store=store)
        claim_legacy_device(session, tenant_id=tenant_b.id, device_id="device-2", actor=owner_b, gateway_store=store)
        rows = list_tenant_devices(session, tenant_id=tenant_a.id, gateway_store=store)
        assert [row["device_id"] for row in rows] == ["device-1"]
        assert all("credential_hash" not in row for row in rows)
