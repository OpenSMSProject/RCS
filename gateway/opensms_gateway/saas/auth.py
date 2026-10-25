from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Membership, SessionRecord, Tenant, TenantRole, TenantStatus, User
from .security import hash_session_token


@dataclass(frozen=True)
class Principal:
    user_id: Optional[UUID]
    tenant_id: Optional[UUID]
    role: Optional[TenantRole]
    is_super_admin: bool = False


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def authenticate_session(session: Session, raw_token: str, *, now: Optional[datetime] = None) -> Principal:
    now = now or datetime.now(timezone.utc)
    token_hash = hash_session_token(raw_token)
    record = session.scalar(select(SessionRecord).where(SessionRecord.token_hash == token_hash))
    if record is None or record.revoked_at is not None or _aware(record.expires_at) <= _aware(now):
        raise HTTPException(status_code=401, detail="invalid session")
    user = session.get(User, record.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if record.tenant_id is None:
        if not user.is_super_admin:
            raise HTTPException(status_code=403, detail="tenant context required")
        return Principal(user_id=user.id, tenant_id=None, role=None, is_super_admin=True)
    tenant = session.get(Tenant, record.tenant_id)
    if tenant is None or tenant.status == TenantStatus.suspended:
        raise HTTPException(status_code=403, detail="tenant unavailable")
    membership = session.scalar(
        select(Membership).where(
            Membership.tenant_id == record.tenant_id,
            Membership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="membership required")
    return Principal(
        user_id=user.id,
        tenant_id=record.tenant_id,
        role=membership.role,
        is_super_admin=False,
    )


def require_role(*roles: TenantRole) -> Callable[[Principal], Principal]:
    allowed = frozenset(roles)
    if not allowed:
        raise ValueError("at least one tenant role is required")

    def dependency(principal: Principal) -> Principal:
        if principal.is_super_admin or principal.tenant_id is None or principal.role not in allowed:
            raise HTTPException(status_code=403, detail="forbidden")
        return principal

    return dependency


def require_super_admin() -> Callable[[Principal], Principal]:
    def dependency(principal: Principal) -> Principal:
        if not principal.is_super_admin:
            raise HTTPException(status_code=403, detail="forbidden")
        return principal

    return dependency
