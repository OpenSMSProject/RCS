from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from .models import Membership, SessionRecord, Tenant, TenantRole, TenantStatus, User
from .security import hash_session_token


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    tenant_id: Optional[UUID]
    role: Optional[TenantRole]
    is_super_admin: bool
    tenant_status: Optional[TenantStatus] = None


def require_role(*roles: TenantRole):
    allowed = set(roles)

    def guard(principal: Principal) -> Principal:
        if principal.tenant_id is None or principal.role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden")
        if principal.tenant_status != TenantStatus.active:
            raise HTTPException(status_code=403, detail="tenant unavailable")
        return principal

    return guard


def require_super_admin():
    def guard(principal: Principal) -> Principal:
        if not principal.is_super_admin:
            raise HTTPException(status_code=403, detail="forbidden")
        return principal

    return guard


def load_session_principal(session, raw_token: str, *, now: Optional[datetime] = None) -> Optional[Principal]:
    now = now or datetime.now(timezone.utc)
    token_hash = hash_session_token(raw_token)
    record = session.scalar(
        select(SessionRecord).where(
            SessionRecord.token_hash == token_hash,
            SessionRecord.revoked_at.is_(None),
            SessionRecord.expires_at > now,
        )
    )
    if record is None:
        return None

    user = session.get(User, record.user_id)
    if user is None:
        return None
    if record.tenant_id is None:
        return Principal(user.id, None, None, bool(user.is_super_admin), None)

    tenant = session.get(Tenant, record.tenant_id)
    if tenant is None:
        return None
    membership = session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant.id,
            Membership.user_id == user.id,
        )
    )
    if membership is None:
        return None
    return Principal(user.id, tenant.id, membership.role, bool(user.is_super_admin), tenant.status)
