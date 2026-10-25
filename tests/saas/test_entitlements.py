import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.entitlements import EntitlementDecision, evaluate_entitlement, validate_plan_assignment
from opensms_gateway.saas.models import (
    ApiKey, Base, Membership, Plan, TenantDevice, TenantEntitlement, TenantRole,
    TenantType, Trial, User,
)
from opensms_gateway.saas.tenants import provision_trial_tenant


def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_pf(session):
    return provision_trial_tenant(
        session, email="owner@example.com", password="password-123",
        tenant_type=TenantType.PF, document_number="12345678901", display_name="PF",
    )


def test_default_trial_entitlements_and_exact_limits():
    session = db(); tenant = make_pf(session); now = datetime.now(timezone.utc)
    users = evaluate_entitlement(session, tenant_id=tenant.id, capability="users", now=now)
    devices = evaluate_entitlement(session, tenant_id=tenant.id, capability="devices", now=now)
    api_keys = evaluate_entitlement(session, tenant_id=tenant.id, capability="api_keys", now=now)
    external_api = evaluate_entitlement(session, tenant_id=tenant.id, capability="external_api", now=now)
    bulk = evaluate_entitlement(session, tenant_id=tenant.id, capability="bulk_campaigns", now=now)
    assert users == EntitlementDecision(True, None, 2, 1)
    assert devices == EntitlementDecision(True, None, 1, 0)
    assert api_keys == EntitlementDecision(True, None, 1, 0)
    assert external_api.allowed is True
    assert bulk.allowed is False and bulk.reason == "not_entitled"

    second = User(email="two@example.com", password_hash="hash")
    session.add(second); session.flush()
    session.add(Membership(tenant_id=tenant.id, user_id=second.id, role=TenantRole.Operator))
    session.add(TenantDevice(tenant_id=tenant.id, device_id="dev-1"))
    session.add(ApiKey(tenant_id=tenant.id, label="one", key_hash="kh", key_prefix="osms_live_one"))
    session.commit()
    assert evaluate_entitlement(session, tenant_id=tenant.id, capability="users", now=now).allowed is False
    assert evaluate_entitlement(session, tenant_id=tenant.id, capability="devices", now=now).allowed is False
    assert evaluate_entitlement(session, tenant_id=tenant.id, capability="api_keys", now=now).allowed is False


def test_trial_expiry_blocks_new_entitled_actions_but_does_not_delete_state():
    session = db(); tenant = make_pf(session); now = datetime.now(timezone.utc)
    trial = session.scalar(select(Trial).where(Trial.tenant_id == tenant.id))
    trial.expires_at = now
    session.commit()
    decision = evaluate_entitlement(session, tenant_id=tenant.id, capability="devices", now=now)
    assert decision.allowed is False and decision.reason == "trial_expired"
    assert session.get(type(tenant), tenant.id) is not None
    assert evaluate_entitlement(session, tenant_id=tenant.id, capability="external_api", now=now).allowed is False


def test_pf_and_pj_plan_catalogs_cannot_cross_assign_and_plan_overrides_trial():
    session = db(); tenant = make_pf(session); now = datetime.now(timezone.utc)
    pf_plan = Plan(code="pf-pro", name="PF Pro", tenant_type=TenantType.PF, max_users=5, max_devices=3, max_api_keys=2, monthly_messages=10000, external_api=True, bulk_campaigns=True)
    pj_plan = Plan(code="pj-pro", name="PJ Pro", tenant_type=TenantType.PJ, max_users=20, max_devices=10, max_api_keys=10, monthly_messages=100000)
    session.add_all([pf_plan, pj_plan]); session.commit()
    validate_plan_assignment(session, tenant_id=tenant.id, plan_id=pf_plan.id)
    with pytest.raises(ValueError, match="tenant type"):
        validate_plan_assignment(session, tenant_id=tenant.id, plan_id=pj_plan.id)
    entitlement = TenantEntitlement(tenant_id=tenant.id, plan_id=pf_plan.id)
    session.add(entitlement); session.commit()
    users = evaluate_entitlement(session, tenant_id=tenant.id, capability="users", now=now + timedelta(days=30))
    assert users.allowed is True and users.limit == 5 and users.used == 1
    assert evaluate_entitlement(session, tenant_id=tenant.id, capability="bulk_campaigns", now=now + timedelta(days=30)).allowed is True


def test_courtesy_overrides_replace_active_trial_limits_and_booleans():
    session = db(); tenant = make_pf(session); now = datetime.now(timezone.utc)
    session.add(TenantDevice(tenant_id=tenant.id, device_id="dev-1"))
    session.add(TenantEntitlement(
        tenant_id=tenant.id,
        plan_id=None,
        courtesy_overrides={"devices": 3, "external_api": False, "bulk_campaigns": True},
    ))
    session.commit()

    devices = evaluate_entitlement(session, tenant_id=tenant.id, capability="devices", now=now)
    assert devices == EntitlementDecision(True, None, 3, 1)
    external_api = evaluate_entitlement(session, tenant_id=tenant.id, capability="external_api", now=now)
    assert external_api.allowed is False and external_api.reason == "not_entitled"
    bulk = evaluate_entitlement(session, tenant_id=tenant.id, capability="bulk_campaigns", now=now)
    assert bulk.allowed is True and bulk.reason is None


def test_courtesy_override_does_not_reactivate_an_expired_trial():
    session = db(); tenant = make_pf(session); now = datetime.now(timezone.utc)
    trial = session.scalar(select(Trial).where(Trial.tenant_id == tenant.id))
    trial.expires_at = now
    session.add(TenantEntitlement(tenant_id=tenant.id, plan_id=None, courtesy_overrides={"devices": 5}))
    session.commit()
    decision = evaluate_entitlement(session, tenant_id=tenant.id, capability="devices", now=now)
    assert decision.allowed is False and decision.reason == "trial_expired"


def test_unknown_capability_is_rejected_in_one_place():
    session = db(); tenant = make_pf(session)
    with pytest.raises(ValueError, match="capability"):
        evaluate_entitlement(session, tenant_id=tenant.id, capability="made_up", now=datetime.now(timezone.utc))
