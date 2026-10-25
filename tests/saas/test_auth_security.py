import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.auth import Principal, authenticate_session, require_role, require_super_admin
from opensms_gateway.saas.models import Base, DocumentType, Membership, SessionRecord, Tenant, TenantRole, TenantStatus, TenantType, User
from opensms_gateway.saas.security import hash_password, hash_session_token, new_session_token, verify_password


def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_passwords_use_argon2_and_verify_safely():
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2")
    assert "correct horse battery staple" not in encoded
    assert verify_password("correct horse battery staple", encoded) is True
    assert verify_password("wrong", encoded) is False
    assert verify_password("wrong", "malformed") is False


def test_session_tokens_are_high_entropy_and_stored_nonrecoverably():
    first = new_session_token(); second = new_session_token()
    assert first != second
    assert len(first) >= 40
    encoded = hash_session_token(first)
    assert len(encoded) == 64
    assert first not in encoded
    assert hash_session_token(first) == encoded


def test_session_authentication_respects_expiry_revocation_and_suspension():
    session = db(); now = datetime.now(timezone.utc)
    tenant = Tenant(tenant_type=TenantType.PF, document_type=DocumentType.CPF, document_number="11122233344", display_name="PF")
    user = User(email="owner@example.com", password_hash="hash")
    session.add_all([tenant, user]); session.flush()
    session.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.Owner)); session.flush()
    raw = new_session_token()
    record = SessionRecord(user_id=user.id, tenant_id=tenant.id, token_hash=hash_session_token(raw), expires_at=now + timedelta(hours=1))
    session.add(record); session.commit()
    principal = authenticate_session(session, raw, now=now)
    assert principal.user_id == user.id and principal.tenant_id == tenant.id and principal.role == TenantRole.Owner
    record.revoked_at = now; session.commit()
    with pytest.raises(HTTPException) as revoked:
        authenticate_session(session, raw, now=now)
    assert revoked.value.status_code == 401
    record.revoked_at = None; record.expires_at = now - timedelta(seconds=1); session.commit()
    with pytest.raises(HTTPException) as expired:
        authenticate_session(session, raw, now=now)
    assert expired.value.status_code == 401
    record.expires_at = now + timedelta(hours=1); tenant.status = TenantStatus.suspended; session.commit()
    with pytest.raises(HTTPException) as suspended:
        authenticate_session(session, raw, now=now)
    assert suspended.value.status_code == 403


def test_role_guards_are_explicit_and_super_admin_is_separate():
    tenant_id = uuid4()
    owner = Principal(user_id=uuid4(), tenant_id=tenant_id, role=TenantRole.Owner, is_super_admin=False)
    admin = Principal(user_id=uuid4(), tenant_id=tenant_id, role=TenantRole.Admin, is_super_admin=False)
    operator = Principal(user_id=uuid4(), tenant_id=tenant_id, role=TenantRole.Operator, is_super_admin=False)
    super_admin = Principal(user_id=uuid4(), tenant_id=None, role=None, is_super_admin=True)
    assert require_role(TenantRole.Owner)(owner) is owner
    assert require_role(TenantRole.Owner, TenantRole.Admin)(admin) is admin
    with pytest.raises(HTTPException) as denied:
        require_role(TenantRole.Owner)(operator)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException):
        require_super_admin()(owner)
    assert require_super_admin()(super_admin) is super_admin
    with pytest.raises(HTTPException):
        require_role(TenantRole.Owner)(super_admin)
