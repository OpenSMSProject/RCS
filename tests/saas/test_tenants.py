from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _session():
    from gateway.opensms_gateway.saas.models import Base
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_normalize_document_and_pf_pj_mapping():
    from gateway.opensms_gateway.saas.models import DocumentType
    from gateway.opensms_gateway.saas.tenants import normalize_document

    assert normalize_document(DocumentType.CPF, "123.456.789-01") == "12345678901"
    assert normalize_document(DocumentType.CNPJ, "12.345.678/0001-99") == "12345678000199"
    with pytest.raises(ValueError):
        normalize_document(DocumentType.CPF, "123")


def test_provision_creates_first_owner_unverified():
    from gateway.opensms_gateway.saas.models import Membership, TenantRole, TenantType, User
    from gateway.opensms_gateway.saas.tenants import provision_trial_tenant

    with _session() as session:
        tenant = provision_trial_tenant(session, email="OWNER@EXAMPLE.COM", password="strong password", tenant_type=TenantType.PF, document_number="123.456.789-01", display_name="Pessoa")
        membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
        user = session.get(User, membership.user_id)
        assert tenant.document_number == "12345678901"
        assert membership.role == TenantRole.Owner
        assert user.email == "owner@example.com"
        assert user.email_verified is False


def test_pj_infers_cnpj_and_duplicate_document_is_rejected():
    from gateway.opensms_gateway.saas.models import DocumentType, TenantType
    from gateway.opensms_gateway.saas.tenants import provision_trial_tenant

    with _session() as session:
        tenant = provision_trial_tenant(session, email="a@example.com", password="password one", tenant_type=TenantType.PJ, document_number="12.345.678/0001-99", display_name="Empresa")
        assert tenant.document_type == DocumentType.CNPJ
        with pytest.raises(ValueError, match="document"):
            provision_trial_tenant(session, email="b@example.com", password="password two", tenant_type=TenantType.PJ, document_number="12345678000199", display_name="Outra")


def test_email_verification_token_is_one_time():
    from gateway.opensms_gateway.saas.models import TenantType
    from gateway.opensms_gateway.saas.tenants import issue_email_verification, provision_trial_tenant, verify_email_token

    with _session() as session:
        tenant = provision_trial_tenant(session, email="verify@example.com", password="password", tenant_type=TenantType.PF, document_number="111.222.333-44", display_name="Verify")
        user = session.scalar(select(__import__("gateway.opensms_gateway.saas.models", fromlist=["User"]).User).where(__import__("gateway.opensms_gateway.saas.models", fromlist=["User"]).User.email == "verify@example.com"))
        token_record, raw = issue_email_verification(session, user_id=user.id)
        verified = verify_email_token(session, raw_token=raw)
        assert verified.email_verified is True
        assert token_record.used_at is not None
        with pytest.raises(ValueError, match="invalid or expired"):
            verify_email_token(session, raw_token=raw)


def test_admin_cannot_promote_owner_and_last_owner_cannot_be_demoted():
    from gateway.opensms_gateway.saas.auth import Principal
    from gateway.opensms_gateway.saas.models import Membership, TenantRole, TenantStatus, TenantType
    from gateway.opensms_gateway.saas.tenants import change_member_role, invite_member, provision_trial_tenant

    with _session() as session:
        tenant = provision_trial_tenant(session, email="owner@example.com", password="password", tenant_type=TenantType.PF, document_number="999.888.777-66", display_name="Roles")
        owner_membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
        owner = Principal(owner_membership.user_id, tenant.id, TenantRole.Owner, False, TenantStatus.active)
        admin_membership = invite_member(session, tenant_id=tenant.id, actor=owner, email="admin@example.com", role=TenantRole.Admin)
        admin = Principal(admin_membership.user_id, tenant.id, TenantRole.Admin, False, TenantStatus.active)
        with pytest.raises(PermissionError):
            invite_member(session, tenant_id=tenant.id, actor=admin, email="new-owner@example.com", role=TenantRole.Owner)
        with pytest.raises(ValueError, match="last Owner"):
            change_member_role(session, membership_id=owner_membership.id, actor=owner, role=TenantRole.Admin)
