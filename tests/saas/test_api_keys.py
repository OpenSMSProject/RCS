import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


def _session():
    from gateway.opensms_gateway.saas.models import Base
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _tenant_owner(session, email="owner@example.com", doc="123.456.789-01"):
    from gateway.opensms_gateway.saas.auth import Principal
    from gateway.opensms_gateway.saas.models import Membership, TenantRole, TenantStatus, TenantType
    from gateway.opensms_gateway.saas.tenants import provision_trial_tenant
    tenant = provision_trial_tenant(session, email=email, password="password", tenant_type=TenantType.PF, document_number=doc, display_name="Tenant")
    membership = session.scalar(select(Membership).where(Membership.tenant_id == tenant.id))
    return tenant, Principal(membership.user_id, tenant.id, TenantRole.Owner, False, TenantStatus.active)


def test_api_key_raw_value_returned_once_and_hash_stored():
    from gateway.opensms_gateway.saas.api_keys import create_api_key

    with _session() as session:
        tenant, owner = _tenant_owner(session)
        key, raw = create_api_key(session, tenant_id=tenant.id, actor=owner, label="integration")
        assert raw.startswith("osms_live_")
        assert raw not in key.key_hash
        assert len(key.key_hash) == 64


def test_trial_allows_only_one_active_api_key():
    from gateway.opensms_gateway.saas.api_keys import create_api_key

    with _session() as session:
        tenant, owner = _tenant_owner(session)
        create_api_key(session, tenant_id=tenant.id, actor=owner, label="one")
        with pytest.raises(ValueError, match="limit"):
            create_api_key(session, tenant_id=tenant.id, actor=owner, label="two")


def test_revoked_key_cannot_authenticate_and_cross_tenant_revoke_is_denied():
    from gateway.opensms_gateway.saas.api_keys import authenticate_api_key, create_api_key, revoke_api_key

    with _session() as session:
        tenant_a, owner_a = _tenant_owner(session, "a@example.com", "111.222.333-44")
        tenant_b, owner_b = _tenant_owner(session, "b@example.com", "555.666.777-88")
        key, raw = create_api_key(session, tenant_id=tenant_a.id, actor=owner_a, label="a")
        principal = authenticate_api_key(session, raw)
        assert principal.tenant_id == tenant_a.id
        with pytest.raises(PermissionError):
            revoke_api_key(session, key_id=key.id, actor=owner_b)
        revoke_api_key(session, key_id=key.id, actor=owner_a)
        assert authenticate_api_key(session, raw) is None


def test_authentication_updates_last_used_at():
    from gateway.opensms_gateway.saas.api_keys import authenticate_api_key, create_api_key

    with _session() as session:
        tenant, owner = _tenant_owner(session)
        key, raw = create_api_key(session, tenant_id=tenant.id, actor=owner, label="usage")
        assert key.last_used_at is None
        authenticate_api_key(session, raw)
        session.refresh(key)
        assert key.last_used_at is not None
