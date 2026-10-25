import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_password_hash_uses_argon2_and_verifies():
    from gateway.opensms_gateway.saas.security import hash_password, verify_password

    encoded = hash_password("correct horse battery staple")
    assert encoded != "correct horse battery staple"
    assert "argon2" in encoded.lower()
    assert verify_password("correct horse battery staple", encoded) is True
    assert verify_password("wrong", encoded) is False


def test_session_tokens_are_high_entropy_and_nonrecoverable():
    from gateway.opensms_gateway.saas.security import new_session_token, hash_session_token

    raw = new_session_token()
    encoded = hash_session_token(raw)
    assert len(raw) >= 40
    assert raw not in encoded
    assert len(encoded) == 64


def test_role_guards_and_super_admin_are_separate():
    from gateway.opensms_gateway.saas.auth import Principal, require_role, require_super_admin
    from gateway.opensms_gateway.saas.models import TenantRole, TenantStatus

    tenant_id = uuid.uuid4()
    owner = Principal(uuid.uuid4(), tenant_id, TenantRole.Owner, False, TenantStatus.active)
    admin = Principal(uuid.uuid4(), tenant_id, TenantRole.Admin, False, TenantStatus.active)
    operator = Principal(uuid.uuid4(), tenant_id, TenantRole.Operator, False, TenantStatus.active)
    super_admin = Principal(uuid.uuid4(), None, None, True, None)

    assert require_role(TenantRole.Owner)(owner) is owner
    assert require_role(TenantRole.Admin, TenantRole.Owner)(admin) is admin
    with pytest.raises(HTTPException) as exc:
        require_role(TenantRole.Owner)(operator)
    assert exc.value.status_code == 403
    assert require_super_admin()(super_admin) is super_admin
    with pytest.raises(HTTPException):
        require_super_admin()(owner)


def test_suspended_tenant_is_denied_by_role_guard():
    from gateway.opensms_gateway.saas.auth import Principal, require_role
    from gateway.opensms_gateway.saas.models import TenantRole, TenantStatus

    principal = Principal(uuid.uuid4(), uuid.uuid4(), TenantRole.Owner, False, TenantStatus.suspended)
    with pytest.raises(HTTPException) as exc:
        require_role(TenantRole.Owner)(principal)
    assert exc.value.status_code == 403


def test_session_record_expiry_and_revocation_are_enforced():
    from gateway.opensms_gateway.saas.auth import load_session_principal
    from gateway.opensms_gateway.saas.models import Base, DocumentType, Membership, SessionRecord, Tenant, TenantRole, TenantType, User
    from gateway.opensms_gateway.saas.security import hash_session_token

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        tenant = Tenant(tenant_type=TenantType.PF, document_type=DocumentType.CPF, document_number="12345678901", display_name="Tenant")
        user = User(email="owner@example.com", password_hash="hash", email_verified=True)
        session.add_all([tenant, user]); session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.Owner))
        session.add(SessionRecord(user_id=user.id, tenant_id=tenant.id, token_hash=hash_session_token("valid-token"), expires_at=now + timedelta(hours=1)))
        session.add(SessionRecord(user_id=user.id, tenant_id=tenant.id, token_hash=hash_session_token("expired-token"), expires_at=now - timedelta(seconds=1)))
        session.add(SessionRecord(user_id=user.id, tenant_id=tenant.id, token_hash=hash_session_token("revoked-token"), expires_at=now + timedelta(hours=1), revoked_at=now))
        session.commit()
        assert load_session_principal(session, "valid-token", now=now).tenant_id == tenant.id
        assert load_session_principal(session, "expired-token", now=now) is None
        assert load_session_principal(session, "revoked-token", now=now) is None
