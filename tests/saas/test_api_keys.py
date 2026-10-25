import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.api_keys import authenticate_api_key, create_api_key, revoke_api_key
from opensms_gateway.saas.auth import Principal
from opensms_gateway.saas.models import ApiKey, AuditEvent, Base, Membership, TenantRole, TenantType
from opensms_gateway.saas.tenants import invite_member, provision_trial_tenant


def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def tenant_with_owner(session, *, email, document, tenant_type=TenantType.PF):
    tenant = provision_trial_tenant(
        session,
        email=email,
        password="password-123",
        tenant_type=tenant_type,
        document_number=document,
        display_name=email,
    )
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    owner = Principal(user_id=membership.user_id, tenant_id=tenant.id, role=TenantRole.Owner, is_super_admin=False)
    return tenant, owner


def test_create_key_returns_raw_once_and_stores_only_hash_with_audit():
    session = db(); tenant, owner = tenant_with_owner(session, email="one@example.com", document="12345678901")
    record, raw = create_api_key(session, tenant_id=tenant.id, actor=owner, label="ERP")
    assert raw.startswith("osms_live_")
    assert raw not in record.key_hash
    assert len(record.key_hash) == 64
    assert record.key_prefix.startswith("osms_live_")
    stored = session.get(ApiKey, record.id)
    assert stored.label == "ERP" and stored.tenant_id == tenant.id and stored.revoked_at is None
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "api_key.created"))
    assert audit is not None and audit.tenant_id == tenant.id and raw not in str(audit.details)


def test_trial_allows_only_one_active_api_key():
    session = db(); tenant, owner = tenant_with_owner(session, email="one@example.com", document="12345678901")
    create_api_key(session, tenant_id=tenant.id, actor=owner, label="first")
    with pytest.raises(PermissionError, match="limit"):
        create_api_key(session, tenant_id=tenant.id, actor=owner, label="second")


def test_authentication_returns_least_privilege_principal_and_updates_last_used():
    session = db(); tenant, owner = tenant_with_owner(session, email="one@example.com", document="12345678901")
    record, raw = create_api_key(session, tenant_id=tenant.id, actor=owner, label="API")
    before = datetime.now(timezone.utc)
    principal = authenticate_api_key(session, raw)
    session.refresh(record)
    assert principal.tenant_id == tenant.id
    assert principal.role == TenantRole.Operator
    assert principal.is_super_admin is False
    assert record.last_used_at is not None and record.last_used_at.replace(tzinfo=timezone.utc) >= before
    with pytest.raises(HTTPException) as bad:
        authenticate_api_key(session, raw + "x")
    assert bad.value.status_code == 401


def test_revoked_key_fails_authentication_and_revocation_is_audited():
    session = db(); tenant, owner = tenant_with_owner(session, email="one@example.com", document="12345678901")
    record, raw = create_api_key(session, tenant_id=tenant.id, actor=owner, label="API")
    revoke_api_key(session, key_id=record.id, actor=owner)
    session.refresh(record)
    assert record.revoked_at is not None
    with pytest.raises(HTTPException) as revoked:
        authenticate_api_key(session, raw)
    assert revoked.value.status_code == 401
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "api_key.revoked"))
    assert audit is not None and audit.target_id == str(record.id)


def test_operator_cannot_manage_keys_and_cross_tenant_probe_looks_missing():
    session = db()
    tenant_a, owner_a = tenant_with_owner(session, email="a@example.com", document="12345678901")
    tenant_b, owner_b = tenant_with_owner(session, email="b@example.com", document="98765432100")
    key_a, _ = create_api_key(session, tenant_id=tenant_a.id, actor=owner_a, label="A")
    membership = invite_member(session, tenant_id=tenant_b.id, actor=owner_b, email="operator@example.com", role=TenantRole.Operator)
    operator_b = Principal(user_id=membership.user_id, tenant_id=tenant_b.id, role=TenantRole.Operator, is_super_admin=False)
    with pytest.raises(PermissionError):
        create_api_key(session, tenant_id=tenant_b.id, actor=operator_b, label="bad")
    with pytest.raises(LookupError, match="not found"):
        revoke_api_key(session, key_id=key_a.id, actor=owner_b)
    with pytest.raises(LookupError, match="not found"):
        revoke_api_key(session, key_id=uuid4(), actor=owner_b)
