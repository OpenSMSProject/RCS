import os
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.auth import Principal
from opensms_gateway.saas.models import (
    Base, DocumentType, EmailVerificationToken, Membership, Tenant, TenantEntitlement,
    TenantRole, TenantStatus, TenantType, Trial, User,
)
from opensms_gateway.saas.tenants import change_member_role, invite_member, normalize_document, provision_trial_tenant


def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_document_normalization_and_type_lengths():
    assert normalize_document(DocumentType.CPF, "123.456.789-01") == "12345678901"
    assert normalize_document(DocumentType.CNPJ, "12.345.678/0001-99") == "12345678000199"
    with pytest.raises(ValueError, match="CPF"):
        normalize_document(DocumentType.CPF, "123")
    with pytest.raises(ValueError, match="CNPJ"):
        normalize_document(DocumentType.CNPJ, "123")


def test_provision_pf_trial_creates_owner_and_verification_state():
    session = db()
    before = datetime.now(timezone.utc)
    tenant = provision_trial_tenant(
        session,
        email=" Owner@Example.com ",
        password="correct horse battery staple",
        tenant_type=TenantType.PF,
        document_number="123.456.789-01",
        display_name="Pessoa Teste",
    )
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    user = session.get(User, membership.user_id)
    trial = session.scalar(select(Trial).where(Trial.tenant_id == tenant.id))
    verification = session.scalar(select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id))
    assert tenant.document_type == DocumentType.CPF
    assert tenant.document_number == "12345678901"
    assert membership.role == TenantRole.Owner
    assert user.email == "owner@example.com" and user.email_verified is False
    assert trial.max_users == 2 and trial.max_devices == 1 and trial.max_api_keys == 1
    assert trial.message_allowance == 200 and trial.external_api is True and trial.bulk_campaigns is False
    assert 6.99 <= (trial.expires_at.replace(tzinfo=timezone.utc) - before).total_seconds() / 86400 <= 7.01
    assert verification is not None and len(verification.token_hash) == 64


def test_provision_pj_maps_to_cnpj_and_rejects_duplicate_document_or_email():
    session = db()
    first = provision_trial_tenant(
        session, email="first@example.com", password="password-123",
        tenant_type=TenantType.PJ, document_number="12.345.678/0001-99", display_name="Org A",
    )
    assert first.document_type == DocumentType.CNPJ
    with pytest.raises(ValueError, match="document"):
        provision_trial_tenant(
            session, email="other@example.com", password="password-123",
            tenant_type=TenantType.PJ, document_number="12345678000199", display_name="Org B",
        )
    with pytest.raises(ValueError, match="email"):
        provision_trial_tenant(
            session, email="first@example.com", password="password-123",
            tenant_type=TenantType.PF, document_number="98765432100", display_name="Pessoa",
        )
    assert session.scalar(select(Tenant).where(Tenant.document_number == "12345678000199")).id == first.id


def test_trial_user_limit_is_enforced_when_inviting_members():
    session = db()
    tenant = provision_trial_tenant(
        session, email="owner@example.com", password="password-123",
        tenant_type=TenantType.PF, document_number="12345678901", display_name="PF",
    )
    owner_membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    owner = Principal(user_id=owner_membership.user_id, tenant_id=tenant.id, role=TenantRole.Owner, is_super_admin=False)
    invite_member(session, tenant_id=tenant.id, actor=owner, email="second@example.com", role=TenantRole.Admin)
    with pytest.raises(PermissionError, match="user limit"):
        invite_member(session, tenant_id=tenant.id, actor=owner, email="third@example.com", role=TenantRole.Operator)


def test_membership_permissions_prevent_owner_escalation_and_last_owner_demotion():
    session = db()
    tenant = provision_trial_tenant(
        session, email="owner@example.com", password="password-123",
        tenant_type=TenantType.PF, document_number="12345678901", display_name="PF",
    )
    owner_membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    owner = Principal(user_id=owner_membership.user_id, tenant_id=tenant.id, role=TenantRole.Owner, is_super_admin=False)
    admin_membership = invite_member(session, tenant_id=tenant.id, actor=owner, email="admin@example.com", role=TenantRole.Admin)
    admin = Principal(user_id=admin_membership.user_id, tenant_id=tenant.id, role=TenantRole.Admin, is_super_admin=False)
    session.add(TenantEntitlement(tenant_id=tenant.id, plan_id=None, courtesy_overrides={"users": 3}))
    session.commit()
    operator_membership = invite_member(session, tenant_id=tenant.id, actor=admin, email="operator@example.com", role=TenantRole.Operator)
    operator = Principal(user_id=operator_membership.user_id, tenant_id=tenant.id, role=TenantRole.Operator, is_super_admin=False)
    assert operator_membership.role == TenantRole.Operator
    with pytest.raises(PermissionError):
        invite_member(session, tenant_id=tenant.id, actor=admin, email="bad-owner@example.com", role=TenantRole.Owner)
    with pytest.raises(PermissionError):
        invite_member(session, tenant_id=tenant.id, actor=operator, email="bad@example.com", role=TenantRole.Operator)
    with pytest.raises(ValueError, match="last Owner"):
        change_member_role(session, membership_id=owner_membership.id, actor=owner, role=TenantRole.Admin)
    second_owner = change_member_role(session, membership_id=admin_membership.id, actor=owner, role=TenantRole.Owner)
    assert second_owner.role == TenantRole.Owner
    demoted = change_member_role(session, membership_id=owner_membership.id, actor=owner, role=TenantRole.Admin)
    assert demoted.role == TenantRole.Admin


def test_suspended_tenant_blocks_membership_mutation():
    session = db()
    tenant = provision_trial_tenant(
        session, email="owner@example.com", password="password-123",
        tenant_type=TenantType.PF, document_number="12345678901", display_name="PF",
    )
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    actor = Principal(user_id=membership.user_id, tenant_id=tenant.id, role=TenantRole.Owner, is_super_admin=False)
    tenant.status = TenantStatus.suspended; session.commit()
    with pytest.raises(PermissionError):
        invite_member(session, tenant_id=tenant.id, actor=actor, email="new@example.com", role=TenantRole.Operator)
