import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _session():
    from gateway.opensms_gateway.saas.models import Base
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _owner(session, email, doc):
    from gateway.opensms_gateway.saas.auth import Principal
    from gateway.opensms_gateway.saas.models import Membership, TenantRole, TenantStatus, TenantType
    from gateway.opensms_gateway.saas.tenants import provision_trial_tenant
    tenant = provision_trial_tenant(session, email=email, password="strong password", tenant_type=TenantType.PF, document_number=doc, display_name=email)
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    return tenant, Principal(membership.user_id, tenant.id, TenantRole.Owner, False, TenantStatus.active)


def test_cross_tenant_membership_and_api_key_mutations_are_denied():
    from gateway.opensms_gateway.saas.api_keys import create_api_key, revoke_api_key
    from gateway.opensms_gateway.saas.models import Membership, TenantRole
    from gateway.opensms_gateway.saas.tenants import change_member_role, invite_member

    with _session() as session:
        tenant_a, owner_a = _owner(session, "a@example.com", "111.222.333-44")
        tenant_b, owner_b = _owner(session, "b@example.com", "555.666.777-88")
        member_b = invite_member(session, tenant_id=tenant_b.id, actor=owner_b, email="b2@example.com", role=TenantRole.Operator)
        with pytest.raises(PermissionError):
            change_member_role(session, membership_id=member_b.id, actor=owner_a, role=TenantRole.Admin)
        key_b, _ = create_api_key(session, tenant_id=tenant_b.id, actor=owner_b, label="b")
        with pytest.raises(PermissionError):
            revoke_api_key(session, key_id=key_b.id, actor=owner_a)


def test_tenant_owner_cannot_execute_platform_action():
    from gateway.opensms_gateway.saas.audit import suspend_tenant

    with _session() as session:
        tenant, owner = _owner(session, "a@example.com", "111.222.333-44")
        with pytest.raises(PermissionError):
            suspend_tenant(session, tenant_id=tenant.id, actor=owner)
