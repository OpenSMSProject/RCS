import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import Principal
from .models import (
    DocumentType,
    EmailVerificationToken,
    Membership,
    Tenant,
    TenantRole,
    TenantStatus,
    TenantType,
    Trial,
    User,
)
from .security import hash_password, hash_session_token, new_session_token


_DOCUMENT_LENGTHS = {DocumentType.CPF: 11, DocumentType.CNPJ: 14}


def normalize_document(document_type: DocumentType, value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    expected = _DOCUMENT_LENGTHS[document_type]
    if len(digits) != expected:
        raise ValueError(f"{document_type.value} must contain exactly {expected} digits")
    return digits


def _document_type_for_tenant(tenant_type: TenantType) -> DocumentType:
    if tenant_type == TenantType.PF:
        return DocumentType.CPF
    if tenant_type == TenantType.PJ:
        return DocumentType.CNPJ
    raise ValueError("unsupported tenant type")


def _normalized_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized or "@" not in normalized or len(normalized) > 320:
        raise ValueError("valid email is required")
    return normalized


def provision_trial_tenant(
    session: Session,
    *,
    email: str,
    password: str,
    tenant_type: TenantType,
    document_number: str,
    display_name: str,
) -> Tenant:
    document_type = _document_type_for_tenant(tenant_type)
    document = normalize_document(document_type, document_number)
    normalized_email = _normalized_email(email)
    if session.scalar(select(Tenant.id).where(Tenant.document_number == document)) is not None:
        raise ValueError("document already registered")
    if session.scalar(select(User.id).where(func.lower(User.email) == normalized_email)) is not None:
        raise ValueError("email already registered")
    name = str(display_name or "").strip()
    if not name:
        raise ValueError("display name is required")

    now = datetime.now(timezone.utc)
    tenant = Tenant(
        tenant_type=tenant_type,
        document_type=document_type,
        document_number=document,
        display_name=name,
        status=TenantStatus.active,
    )
    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        email_verified=False,
        is_super_admin=False,
    )
    session.add_all([tenant, user])
    session.flush()
    session.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.Owner))
    session.add(
        Trial(
            tenant_id=tenant.id,
            document_key=f"{document_type.value}:{document}",
            started_at=now,
            expires_at=now + timedelta(days=7),
            max_users=2,
            max_devices=1,
            max_api_keys=1,
            message_allowance=200,
            external_api=True,
            bulk_campaigns=False,
            is_normal_trial=True,
        )
    )
    verification_token = new_session_token()
    session.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_session_token(verification_token),
            expires_at=now + timedelta(hours=24),
        )
    )
    session.commit()
    return tenant


def _tenant_for_actor(session: Session, tenant_id: UUID, actor: Principal) -> Tenant:
    if actor.is_super_admin or actor.tenant_id != tenant_id or actor.role not in {TenantRole.Owner, TenantRole.Admin}:
        raise PermissionError("tenant user management is not allowed")
    tenant = session.get(Tenant, tenant_id)
    if tenant is None or tenant.status != TenantStatus.active:
        raise PermissionError("tenant is unavailable")
    return tenant


def invite_member(
    session: Session,
    *,
    tenant_id: UUID,
    actor: Principal,
    email: str,
    role: TenantRole,
) -> Membership:
    _tenant_for_actor(session, tenant_id, actor)
    if actor.role == TenantRole.Admin and role == TenantRole.Owner:
        raise PermissionError("Admin cannot grant Owner")
    normalized_email = _normalized_email(email)
    user = session.scalar(select(User).where(func.lower(User.email) == normalized_email))
    if user is None:
        user = User(
            email=normalized_email,
            password_hash=hash_password(new_session_token()),
            email_verified=False,
            is_super_admin=False,
        )
        session.add(user)
        session.flush()
    existing = session.scalar(
        select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user.id)
    )
    if existing is not None:
        raise ValueError("user is already a tenant member")
    membership = Membership(tenant_id=tenant_id, user_id=user.id, role=role)
    session.add(membership)
    session.commit()
    return membership


def change_member_role(
    session: Session,
    *,
    membership_id: UUID,
    actor: Principal,
    role: TenantRole,
) -> Membership:
    membership = session.get(Membership, membership_id)
    if membership is None:
        raise LookupError("membership not found")
    _tenant_for_actor(session, membership.tenant_id, actor)
    if actor.role == TenantRole.Admin and (membership.role == TenantRole.Owner or role == TenantRole.Owner):
        raise PermissionError("Admin cannot manage Owner roles")
    if membership.role == TenantRole.Owner and role != TenantRole.Owner:
        owner_count = session.scalar(
            select(func.count()).select_from(Membership).where(
                Membership.tenant_id == membership.tenant_id,
                Membership.role == TenantRole.Owner,
            )
        )
        if int(owner_count or 0) <= 1:
            raise ValueError("cannot demote the last Owner")
    membership.role = role
    session.commit()
    return membership
