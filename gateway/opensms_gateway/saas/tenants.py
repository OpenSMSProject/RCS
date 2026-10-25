import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select

from .auth import Principal
from .models import (
    DocumentType,
    EmailVerificationToken,
    Membership,
    Tenant,
    TenantRole,
    TenantStatus,
    TenantType,
    User,
)
from .security import hash_password, hash_session_token


def normalize_document(document_type: DocumentType, value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    expected = 11 if document_type == DocumentType.CPF else 14
    if len(digits) != expected:
        raise ValueError(f"{document_type.value} must contain exactly {expected} digits")
    return digits


def _document_type_for_tenant(tenant_type: TenantType) -> DocumentType:
    if tenant_type == TenantType.PF:
        return DocumentType.CPF
    if tenant_type == TenantType.PJ:
        return DocumentType.CNPJ
    raise ValueError("invalid tenant type")


def provision_trial_tenant(
    session,
    *,
    email: str,
    password: str,
    tenant_type: TenantType,
    document_number: str,
    display_name: str,
) -> Tenant:
    document_type = _document_type_for_tenant(tenant_type)
    normalized_document = normalize_document(document_type, document_number)
    normalized_email = (email or "").strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("valid email is required")
    if not display_name or not display_name.strip():
        raise ValueError("display name is required")

    if session.scalar(select(Tenant.id).where(Tenant.document_number == normalized_document)) is not None:
        raise ValueError("document already registered")
    if session.scalar(select(User.id).where(func.lower(User.email) == normalized_email)) is not None:
        raise ValueError("email already registered")

    tenant = Tenant(
        tenant_type=tenant_type,
        document_type=document_type,
        document_number=normalized_document,
        display_name=display_name.strip(),
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
    session.commit()
    session.refresh(tenant)
    return tenant


def issue_email_verification(
    session,
    *,
    user_id: UUID,
    now: Optional[datetime] = None,
    ttl_hours: int = 24,
) -> tuple[EmailVerificationToken, str]:
    user = session.get(User, user_id)
    if user is None:
        raise ValueError("user not found")
    now = now or datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(32)
    record = EmailVerificationToken(
        user_id=user_id,
        token_hash=hash_session_token(raw_token),
        expires_at=now + timedelta(hours=ttl_hours),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record, raw_token


def verify_email_token(session, *, raw_token: str, now: Optional[datetime] = None) -> User:
    now = now or datetime.now(timezone.utc)
    token_hash = hash_session_token(raw_token)
    record = session.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
    )
    if record is None:
        raise ValueError("invalid or expired verification token")
    user = session.get(User, record.user_id)
    if user is None:
        raise ValueError("invalid or expired verification token")
    record.used_at = now
    user.email_verified = True
    session.commit()
    session.refresh(user)
    return user


def _active_actor_for_tenant(actor: Principal, tenant_id: UUID) -> None:
    if actor.tenant_id != tenant_id or actor.tenant_status != TenantStatus.active:
        raise PermissionError("forbidden")


def invite_member(
    session,
    *,
    tenant_id: UUID,
    actor: Principal,
    email: str,
    role: TenantRole,
) -> Membership:
    _active_actor_for_tenant(actor, tenant_id)
    if actor.role == TenantRole.Operator:
        raise PermissionError("forbidden")
    if role == TenantRole.Owner and actor.role != TenantRole.Owner:
        raise PermissionError("only Owner can grant Owner role")

    normalized_email = (email or "").strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("valid email is required")
    user = session.scalar(select(User).where(func.lower(User.email) == normalized_email))
    if user is None:
        user = User(
            email=normalized_email,
            password_hash=hash_password(secrets.token_urlsafe(32)),
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
    session.refresh(membership)
    return membership


def change_member_role(
    session,
    *,
    membership_id: UUID,
    actor: Principal,
    role: TenantRole,
) -> Membership:
    membership = session.get(Membership, membership_id)
    if membership is None:
        raise ValueError("membership not found")
    _active_actor_for_tenant(actor, membership.tenant_id)
    if actor.role == TenantRole.Operator:
        raise PermissionError("forbidden")
    if role == TenantRole.Owner and actor.role != TenantRole.Owner:
        raise PermissionError("only Owner can grant Owner role")
    if membership.role == TenantRole.Owner and role != TenantRole.Owner:
        owners = session.scalar(
            select(func.count(Membership.id)).where(
                Membership.tenant_id == membership.tenant_id,
                Membership.role == TenantRole.Owner,
            )
        )
        if int(owners or 0) <= 1:
            raise ValueError("cannot demote last Owner")
        if actor.role != TenantRole.Owner:
            raise PermissionError("only Owner can demote Owner")
    membership.role = role
    session.commit()
    session.refresh(membership)
    return membership
