import os
import sys

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.auth import Principal
from opensms_gateway.saas.devices import claim_existing_device, list_tenant_devices, release_device
from opensms_gateway.saas.models import Base, Membership, TenantDevice, TenantRole, TenantType
from opensms_gateway.saas.tenants import invite_member, provision_trial_tenant
from opensms_gateway.storage import GatewayStore


def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def gateway():
    return GatewayStore(":memory:")


def make_tenant(session, email, document):
    tenant = provision_trial_tenant(
        session, email=email, password="password-123", tenant_type=TenantType.PF,
        document_number=document, display_name=email,
    )
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    owner = Principal(user_id=membership.user_id, tenant_id=tenant.id, role=TenantRole.Owner, is_super_admin=False)
    return tenant, owner


def test_claim_existing_legacy_device_without_modifying_gateway_record():
    session = db(); store = gateway()
    store.create_device("dev-1", "Phone", "secret")
    tenant, owner = make_tenant(session, "one@example.com", "12345678901")
    before = store.get_device("dev-1")
    mapping = claim_existing_device(session, tenant_id=tenant.id, device_id="dev-1", actor=owner, gateway_store=store)
    assert mapping.tenant_id == tenant.id and mapping.device_id == "dev-1"
    assert store.get_device("dev-1") == before
    assert [row.device_id for row in list_tenant_devices(session, tenant_id=tenant.id, actor=owner)] == ["dev-1"]


def test_trial_device_limit_blocks_second_claim():
    session = db(); store = gateway()
    store.create_device("dev-1", "Phone 1", "secret-1")
    store.create_device("dev-2", "Phone 2", "secret-2")
    tenant, owner = make_tenant(session, "one@example.com", "12345678901")
    claim_existing_device(session, tenant_id=tenant.id, device_id="dev-1", actor=owner, gateway_store=store)
    with pytest.raises(PermissionError, match="limit"):
        claim_existing_device(session, tenant_id=tenant.id, device_id="dev-2", actor=owner, gateway_store=store)


def test_unknown_legacy_device_and_cross_tenant_ownership_do_not_leak():
    session = db(); store = gateway()
    store.create_device("dev-1", "Phone", "secret")
    tenant_a, owner_a = make_tenant(session, "a@example.com", "12345678901")
    tenant_b, owner_b = make_tenant(session, "b@example.com", "98765432100")
    claim_existing_device(session, tenant_id=tenant_a.id, device_id="dev-1", actor=owner_a, gateway_store=store)
    with pytest.raises(LookupError, match="device not available"):
        claim_existing_device(session, tenant_id=tenant_b.id, device_id="dev-1", actor=owner_b, gateway_store=store)
    with pytest.raises(LookupError, match="device not available"):
        claim_existing_device(session, tenant_id=tenant_b.id, device_id="missing", actor=owner_b, gateway_store=store)
    assert list_tenant_devices(session, tenant_id=tenant_b.id, actor=owner_b) == []


def test_release_removes_only_saas_mapping_and_operator_cannot_manage():
    session = db(); store = gateway()
    store.create_device("dev-1", "Phone", "secret")
    tenant, owner = make_tenant(session, "one@example.com", "12345678901")
    mapping = claim_existing_device(session, tenant_id=tenant.id, device_id="dev-1", actor=owner, gateway_store=store)
    operator_membership = invite_member(session, tenant_id=tenant.id, actor=owner, email="op@example.com", role=TenantRole.Operator)
    operator = Principal(user_id=operator_membership.user_id, tenant_id=tenant.id, role=TenantRole.Operator, is_super_admin=False)
    with pytest.raises(PermissionError):
        release_device(session, tenant_id=tenant.id, device_id="dev-1", actor=operator)
    release_device(session, tenant_id=tenant.id, device_id="dev-1", actor=owner)
    assert session.get(TenantDevice, mapping.id) is None
    legacy = store.get_device("dev-1")
    assert legacy is not None and legacy["enabled"] is True
