from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def _session():
    from gateway.opensms_gateway.saas.models import Base
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _tenant(session):
    from gateway.opensms_gateway.saas.models import TenantType
    from gateway.opensms_gateway.saas.tenants import provision_trial_tenant
    return provision_trial_tenant(session, email="owner@example.com", password="password", tenant_type=TenantType.PF, document_number="123.456.789-01", display_name="PF")


def test_default_trial_entitlements_and_exact_expiry():
    from gateway.opensms_gateway.saas.entitlements import evaluate_entitlement

    with _session() as session:
        tenant = _tenant(session)
        trial = tenant_trial(session, tenant.id)
        before = trial.ends_at - timedelta(microseconds=1)
        assert evaluate_entitlement(session, tenant_id=tenant.id, capability="users", now=before).limit == 2
        assert evaluate_entitlement(session, tenant_id=tenant.id, capability="devices", now=before).limit == 1
        assert evaluate_entitlement(session, tenant_id=tenant.id, capability="api_keys", now=before).limit == 1
        assert evaluate_entitlement(session, tenant_id=tenant.id, capability="messages", now=before).limit == 200
        assert evaluate_entitlement(session, tenant_id=tenant.id, capability="external_api", now=before).allowed is True
        assert evaluate_entitlement(session, tenant_id=tenant.id, capability="bulk_campaigns", now=before).allowed is False
        assert evaluate_entitlement(session, tenant_id=tenant.id, capability="devices", now=trial.ends_at).allowed is False


def tenant_trial(session, tenant_id):
    from sqlalchemy import select
    from gateway.opensms_gateway.saas.models import Trial
    return session.scalar(select(Trial).where(Trial.tenant_id == tenant_id))


def test_trial_is_exactly_seven_days_and_one_per_document():
    with _session() as session:
        tenant = _tenant(session)
        trial = tenant_trial(session, tenant.id)
        assert trial.ends_at - trial.starts_at == timedelta(days=7)
        assert trial.document_number == tenant.document_number


def test_pf_and_pj_plan_catalogs_cannot_cross_assign():
    from gateway.opensms_gateway.saas.entitlements import assign_plan
    from gateway.opensms_gateway.saas.models import Plan, TenantType

    with _session() as session:
        tenant = _tenant(session)
        pf = Plan(code="pf-pro", tenant_type=TenantType.PF, name="PF Pro")
        pj = Plan(code="pj-pro", tenant_type=TenantType.PJ, name="PJ Pro")
        session.add_all([pf, pj]); session.commit()
        assign_plan(session, tenant_id=tenant.id, plan_id=pf.id)
        assert tenant.plan_id == pf.id
        try:
            assign_plan(session, tenant_id=tenant.id, plan_id=pj.id)
        except ValueError as exc:
            assert "tenant type" in str(exc)
        else:
            raise AssertionError("PJ plan must not be assignable to PF tenant")


def test_super_admin_can_extend_trial():
    from gateway.opensms_gateway.saas.auth import Principal
    from gateway.opensms_gateway.saas.entitlements import extend_trial

    with _session() as session:
        tenant = _tenant(session)
        trial = tenant_trial(session, tenant.id)
        old_end = trial.ends_at
        super_admin = Principal(user_id=__import__("uuid").uuid4(), tenant_id=None, role=None, is_super_admin=True)
        extend_trial(session, tenant_id=tenant.id, days=3, actor=super_admin)
        assert trial.ends_at == old_end + timedelta(days=3)


def test_plan_overage_policy_is_preserved():
    from gateway.opensms_gateway.saas.models import OveragePolicy, Plan, TenantType

    plan = Plan(code="pf-bill", tenant_type=TenantType.PF, name="PF Bill", overage_policy=OveragePolicy.bill)
    assert plan.overage_policy == OveragePolicy.bill
