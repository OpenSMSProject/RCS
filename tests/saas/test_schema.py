import uuid

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session


def test_schema_defines_phase1_entities_and_enums():
    from gateway.opensms_gateway.saas.models import (
        ApiKey,
        AuditEvent,
        Base,
        DocumentType,
        EmailVerificationToken,
        Membership,
        OveragesPolicy,
        Plan,
        SessionRecord,
        Tenant,
        TenantDevice,
        TenantEntitlement,
        TenantRole,
        TenantStatus,
        TenantType,
        Trial,
        User,
    )

    assert TenantType.PF.value == "PF"
    assert TenantType.PJ.value == "PJ"
    assert DocumentType.CPF.value == "CPF"
    assert DocumentType.CNPJ.value == "CNPJ"
    assert TenantRole.Owner.value == "Owner"
    assert TenantRole.Admin.value == "Admin"
    assert TenantRole.Operator.value == "Operator"
    assert TenantStatus.active.value == "active"
    assert TenantStatus.suspended.value == "suspended"
    assert OveragesPolicy.block.value == "block"
    assert OveragesPolicy.bill.value == "bill"
    assert all(cls.__tablename__ in Base.metadata.tables for cls in [Tenant, User, Membership, Plan, TenantEntitlement, Trial, ApiKey, TenantDevice, AuditEvent, SessionRecord, EmailVerificationToken])


def test_schema_constraints_and_indexes_work_on_sqlite():
    from gateway.opensms_gateway.saas.models import (
        ApiKey,
        Base,
        DocumentType,
        Membership,
        Plan,
        Tenant,
        TenantDevice,
        TenantRole,
        TenantType,
        User,
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    tenant_indexes = {idx["name"] for idx in inspector.get_indexes("tenants")}
    assert "ix_tenants_document_number" in tenant_indexes

    with Session(engine) as session:
        tenant = Tenant(tenant_type=TenantType.PF, document_type=DocumentType.CPF, document_number="12345678901", display_name="PF")
        user = User(email="owner@example.com", password_hash="hash")
        plan = Plan(code="pf-basic", tenant_type=TenantType.PF, name="PF Basic")
        session.add_all([tenant, user, plan])
        session.flush()
        session.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.Owner))
        session.add(ApiKey(tenant_id=tenant.id, label="default", key_hash="hash-key"))
        session.add(TenantDevice(tenant_id=tenant.id, device_id="device-1"))
        session.commit()

    assert inspector.get_unique_constraints("memberships")
    assert inspector.get_unique_constraints("api_keys")
    assert inspector.get_unique_constraints("tenant_devices")


def test_super_admin_is_platform_scoped_not_membership_role():
    from gateway.opensms_gateway.saas.models import TenantRole, User

    user = User(email="super@example.com", password_hash="hash", is_super_admin=True)
    assert user.is_super_admin is True
    assert "SuperAdmin" not in {role.value for role in TenantRole}


def test_email_verification_token_has_one_time_fields():
    from gateway.opensms_gateway.saas.models import EmailVerificationToken

    names = {column.name for column in EmailVerificationToken.__table__.columns}
    assert {"token_hash", "expires_at", "used_at"}.issubset(names)


def test_uuid_primary_keys_are_generated():
    from gateway.opensms_gateway.saas.models import Tenant, TenantType, DocumentType

    tenant = Tenant(tenant_type=TenantType.PJ, document_type=DocumentType.CNPJ, document_number="12345678000199", display_name="PJ")
    default = Tenant.__table__.c.id.default.arg
    generated = default(None) if callable(default) else default
    assert isinstance(generated, uuid.UUID)
