import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.models import (
    ApiKey,
    Base,
    DocumentType,
    EmailVerificationToken,
    Membership,
    Plan,
    Tenant,
    TenantDevice,
    TenantRole,
    TenantType,
    User,
)


def new_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_foundation_tables_and_tenant_indexes_exist():
    engine = new_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "tenants", "users", "memberships", "plans", "tenant_entitlements",
        "trials", "api_keys", "tenant_devices", "audit_events", "session_records",
        "email_verification_tokens",
    } <= tables
    indexes = {i["name"] for i in inspector.get_indexes("memberships")}
    assert "ix_memberships_tenant_id" in indexes


def test_normalized_document_is_unique():
    engine = new_engine()
    with Session(engine) as session:
        session.add(Tenant(tenant_type=TenantType.PF, document_type=DocumentType.CPF, document_number="12345678901", display_name="A"))
        session.commit()
        session.add(Tenant(tenant_type=TenantType.PF, document_type=DocumentType.CPF, document_number="12345678901", display_name="B"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_membership_api_key_token_and_device_uniqueness():
    engine = new_engine()
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        tenant = Tenant(tenant_type=TenantType.PJ, document_type=DocumentType.CNPJ, document_number="12345678000199", display_name="Org")
        user = User(email="owner@example.com", password_hash="hash", is_super_admin=False)
        session.add_all([tenant, user]); session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.Owner))
        session.add(ApiKey(tenant_id=tenant.id, label="main", key_hash="keyhash"))
        session.add(TenantDevice(tenant_id=tenant.id, device_id="device-1"))
        session.add(EmailVerificationToken(user_id=user.id, token_hash="verifyhash", expires_at=now + timedelta(hours=1)))
        session.commit()
        session.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.Admin))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert user.is_super_admin is False


def test_pf_and_pj_plan_catalogs_are_explicit():
    engine = new_engine()
    with Session(engine) as session:
        session.add_all([
            Plan(code="pf-personal", name="PF", tenant_type=TenantType.PF, max_users=2, max_devices=1, max_api_keys=1, monthly_messages=200),
            Plan(code="pj-business", name="PJ", tenant_type=TenantType.PJ, max_users=10, max_devices=5, max_api_keys=5, monthly_messages=50000),
        ])
        session.commit()
        assert {p.tenant_type for p in session.query(Plan).all()} == {TenantType.PF, TenantType.PJ}
