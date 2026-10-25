import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _session():
    from gateway.opensms_gateway.saas.models import Base
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _tenant(session):
    from gateway.opensms_gateway.saas.models import TenantType
    from gateway.opensms_gateway.saas.tenants import provision_trial_tenant
    return provision_trial_tenant(session, email="owner@example.com", password="password", tenant_type=TenantType.PF, document_number="123.456.789-01", display_name="Tenant")


def test_tenant_role_cannot_run_platform_actions():
    from gateway.opensms_gateway.saas.auth import Principal
    from gateway.opensms_gateway.saas.models import TenantRole, TenantStatus
    from gateway.opensms_gateway.saas.audit import suspend_tenant

    with _session() as session:
        tenant = _tenant(session)
        actor = Principal(uuid.uuid4(), tenant.id, TenantRole.Owner, False, TenantStatus.active)
        with pytest.raises(PermissionError):
            suspend_tenant(session, tenant_id=tenant.id, actor=actor)


def test_super_admin_mutations_emit_audit_and_redact_sensitive_metadata():
    from gateway.opensms_gateway.saas.auth import Principal
    from gateway.opensms_gateway.saas.audit import courtesy_entitlement, reactivate_tenant, record_audit, suspend_tenant
    from gateway.opensms_gateway.saas.models import AuditEvent, TenantStatus

    with _session() as session:
        tenant = _tenant(session)
        actor = Principal(uuid.uuid4(), None, None, True, None)
        suspend_tenant(session, tenant_id=tenant.id, actor=actor)
        assert tenant.status == TenantStatus.suspended
        reactivate_tenant(session, tenant_id=tenant.id, actor=actor)
        assert tenant.status == TenantStatus.active
        courtesy_entitlement(session, tenant_id=tenant.id, capability="devices", int_value=3, actor=actor)
        record_audit(session, actor_user_id=actor.user_id, tenant_id=tenant.id, action="diagnostic", target_type="tenant", target_id=str(tenant.id), metadata={"credential":"secret", "message_body":"hello", "safe":"yes"})
        events = session.scalars(select(AuditEvent).order_by(AuditEvent.created_at)).all()
        assert len(events) >= 4
        assert all(event.actor_user_id == actor.user_id for event in events)
        assert events[-1].metadata_json == {"safe":"yes"}


def test_super_admin_can_change_matching_plan_only():
    from gateway.opensms_gateway.saas.auth import Principal
    from gateway.opensms_gateway.saas.audit import change_tenant_plan
    from gateway.opensms_gateway.saas.models import Plan, TenantType

    with _session() as session:
        tenant = _tenant(session)
        pf = Plan(code="pf", tenant_type=TenantType.PF, name="PF")
        pj = Plan(code="pj", tenant_type=TenantType.PJ, name="PJ")
        session.add_all([pf,pj]); session.commit()
        actor = Principal(uuid.uuid4(), None, None, True, None)
        change_tenant_plan(session, tenant_id=tenant.id, plan_id=pf.id, actor=actor)
        assert tenant.plan_id == pf.id
        with pytest.raises(ValueError):
            change_tenant_plan(session, tenant_id=tenant.id, plan_id=pj.id, actor=actor)
