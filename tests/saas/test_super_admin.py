import os
import sys
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.audit import record_audit
from opensms_gateway.saas.auth import Principal
from opensms_gateway.saas.models import (
    AuditEvent, Base, Membership, Plan, TenantEntitlement, TenantRole,
    TenantStatus, TenantType, Trial, User,
)
from opensms_gateway.saas.super_admin import (
    change_plan, extend_trial, reactivate_tenant, set_courtesy_override, suspend_tenant,
)
from opensms_gateway.saas.tenants import provision_trial_tenant


def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_context(session):
    tenant = provision_trial_tenant(
        session, email="owner@example.com", password="password-123",
        tenant_type=TenantType.PF, document_number="12345678901", display_name="PF",
    )
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    owner = Principal(user_id=membership.user_id, tenant_id=tenant.id, role=TenantRole.Owner, is_super_admin=False)
    admin_user = User(email="root@example.com", password_hash="hash", email_verified=True, is_super_admin=True)
    session.add(admin_user); session.commit()
    super_admin = Principal(user_id=admin_user.id, tenant_id=None, role=None, is_super_admin=True)
    return tenant, owner, super_admin


def test_audit_redacts_secret_and_message_content():
    session = db(); tenant, _, super_admin = make_context(session)
    event = record_audit(
        session,
        actor=super_admin,
        tenant_id=tenant.id,
        action="support.test",
        target_type="tenant",
        target_id=str(tenant.id),
        details={"token": "secret-token", "password": "secret-password", "message_body": "hello", "safe": "visible"},
    )
    assert event.details["safe"] == "visible"
    assert event.details["token"] == "[REDACTED]"
    assert event.details["password"] == "[REDACTED]"
    assert event.details["message_body"] == "[REDACTED]"
    rendered = str(event.details)
    assert "secret-token" not in rendered and "secret-password" not in rendered and "hello" not in rendered


def test_only_super_admin_can_suspend_and_reactivate_tenant():
    session = db(); tenant, owner, super_admin = make_context(session)
    with pytest.raises(PermissionError):
        suspend_tenant(session, tenant_id=tenant.id, actor=owner)
    suspend_tenant(session, tenant_id=tenant.id, actor=super_admin)
    session.refresh(tenant); assert tenant.status == TenantStatus.suspended
    reactivate_tenant(session, tenant_id=tenant.id, actor=super_admin)
    session.refresh(tenant); assert tenant.status == TenantStatus.active
    actions = [row.action for row in session.scalars(select(AuditEvent)).all()]
    assert "tenant.suspended" in actions and "tenant.reactivated" in actions


def test_super_admin_can_extend_trial_and_operation_is_audited():
    session = db(); tenant, owner, super_admin = make_context(session)
    trial = session.scalar(select(Trial).where(Trial.tenant_id == tenant.id))
    old_expiry = trial.expires_at
    with pytest.raises(PermissionError):
        extend_trial(session, tenant_id=tenant.id, actor=owner, days=3)
    updated = extend_trial(session, tenant_id=tenant.id, actor=super_admin, days=3)
    assert updated.expires_at - old_expiry == timedelta(days=3)
    assert updated.extended_by_user_id == super_admin.user_id
    assert session.scalar(select(AuditEvent).where(AuditEvent.action == "trial.extended")) is not None


def test_plan_change_enforces_pf_pj_catalog_and_courtesy_override():
    session = db(); tenant, _, super_admin = make_context(session)
    pf_plan = Plan(code="pf-pro", name="PF Pro", tenant_type=TenantType.PF, max_users=5, max_devices=3, max_api_keys=2, monthly_messages=10000)
    pj_plan = Plan(code="pj-pro", name="PJ Pro", tenant_type=TenantType.PJ, max_users=10, max_devices=10, max_api_keys=10, monthly_messages=100000)
    session.add_all([pf_plan, pj_plan]); session.commit()
    with pytest.raises(ValueError, match="tenant type"):
        change_plan(session, tenant_id=tenant.id, plan_id=pj_plan.id, actor=super_admin)
    entitlement = change_plan(session, tenant_id=tenant.id, plan_id=pf_plan.id, actor=super_admin)
    assert entitlement.plan_id == pf_plan.id
    entitlement = set_courtesy_override(session, tenant_id=tenant.id, actor=super_admin, capability="devices", value=5)
    assert entitlement.courtesy_overrides["devices"] == 5
    actions = [row.action for row in session.scalars(select(AuditEvent)).all()]
    assert "tenant.plan_changed" in actions and "tenant.courtesy_override" in actions
