from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from .api_keys import create_api_key
from .audit import suspend_tenant
from .auth import Principal, load_session_principal
from .devices import claim_legacy_device, list_tenant_devices
from .models import ApiKey, Membership, Plan, SessionRecord, Tenant, TenantRole, Trial, User
from .security import hash_session_token, new_session_token, verify_password
from .tenants import provision_trial_tenant, verify_email_token
from .models import TenantType


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    tenant_type: TenantType
    document_number: str
    display_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class VerificationRequest(BaseModel):
    token: str


class ApiKeyCreateRequest(BaseModel):
    label: str


def build_saas_router(session_factory, gateway_store) -> APIRouter:
    router = APIRouter(prefix="/saas/v1", tags=["saas"])

    def db_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def bearer(authorization: Optional[str]) -> Optional[str]:
        if not authorization:
            return None
        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
            return None
        return parts[1]

    def current_auth(authorization: Optional[str] = Header(default=None), session=Depends(db_session)):
        raw = bearer(authorization)
        if raw is None:
            raise HTTPException(status_code=401, detail="authentication required")
        principal = load_session_principal(session, raw)
        if principal is None:
            raise HTTPException(status_code=401, detail="invalid session")
        return principal, raw, session

    @router.post("/signup", status_code=status.HTTP_201_CREATED)
    def signup(payload: SignupRequest, session=Depends(db_session)):
        try:
            tenant = provision_trial_tenant(
                session,
                email=payload.email,
                password=payload.password,
                tenant_type=payload.tenant_type,
                document_number=payload.document_number,
                display_name=payload.display_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"tenant_id": str(tenant.id), "verification_required": True}

    @router.post("/verify-email")
    def verify_email(payload: VerificationRequest, session=Depends(db_session)):
        try:
            user = verify_email_token(session, raw_token=payload.token)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"verified": True, "email": user.email}

    @router.post("/login")
    def login(payload: LoginRequest, session=Depends(db_session)):
        email = payload.email.strip().lower()
        user = session.scalar(select(User).where(User.email == email))
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        if not user.email_verified:
            raise HTTPException(status_code=403, detail="email verification required")
        membership = session.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at))
        if membership is None and not user.is_super_admin:
            raise HTTPException(status_code=403, detail="no active tenant membership")
        tenant_id = membership.tenant_id if membership is not None else None
        if tenant_id is not None:
            tenant = session.get(Tenant, tenant_id)
            if tenant is None or tenant.status.value != "active":
                raise HTTPException(status_code=403, detail="tenant unavailable")
        raw = new_session_token()
        record = SessionRecord(
            user_id=user.id,
            tenant_id=tenant_id,
            token_hash=hash_session_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        session.add(record)
        session.commit()
        return {"session_token": raw, "expires_in": 86400}

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(auth=Depends(current_auth)):
        _, raw, session = auth
        record = session.scalar(select(SessionRecord).where(SessionRecord.token_hash == hash_session_token(raw), SessionRecord.revoked_at.is_(None)))
        if record is not None:
            record.revoked_at = datetime.now(timezone.utc)
            session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/me")
    def me(auth=Depends(current_auth)):
        principal, _, session = auth
        user = session.get(User, principal.user_id)
        return {
            "user_id": str(principal.user_id),
            "email": user.email if user else None,
            "tenant_id": str(principal.tenant_id) if principal.tenant_id else None,
            "role": principal.role.value if principal.role else None,
            "is_super_admin": principal.is_super_admin,
        }

    @router.get("/api-keys")
    def list_api_keys(auth=Depends(current_auth)):
        principal, _, session = auth
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        rows = session.scalars(select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id).order_by(ApiKey.created_at)).all()
        return [{"id": str(row.id), "label": row.label, "created_at": row.created_at, "last_used_at": row.last_used_at, "revoked_at": row.revoked_at} for row in rows]

    @router.post("/api-keys", status_code=status.HTTP_201_CREATED)
    def create_key(payload: ApiKeyCreateRequest, auth=Depends(current_auth)):
        principal, _, session = auth
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        try:
            record, raw = create_api_key(session, tenant_id=principal.tenant_id, actor=principal, label=payload.label)
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=403 if isinstance(exc, PermissionError) else 409, detail=str(exc)) from exc
        return {"id": str(record.id), "label": record.label, "api_key": raw}

    @router.post("/devices/{device_id}/claim", status_code=status.HTTP_201_CREATED)
    def claim_device(device_id: str, auth=Depends(current_auth)):
        principal, _, session = auth
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        try:
            mapping = claim_legacy_device(session, tenant_id=principal.tenant_id, device_id=device_id, actor=principal, gateway_store=gateway_store)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"id": str(mapping.id), "device_id": mapping.device_id}

    @router.get("/devices")
    def devices(auth=Depends(current_auth)):
        principal, _, session = auth
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        return list_tenant_devices(session, tenant_id=principal.tenant_id, gateway_store=gateway_store)

    @router.get("/plans")
    def plans(auth=Depends(current_auth)):
        principal, _, session = auth
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        tenant = session.get(Tenant, principal.tenant_id)
        rows = session.scalars(select(Plan).where(Plan.tenant_type == tenant.tenant_type, Plan.active.is_(True)).order_by(Plan.code)).all()
        return [{"id": str(row.id), "code": row.code, "name": row.name} for row in rows]

    @router.get("/trial")
    def trial(auth=Depends(current_auth)):
        principal, _, session = auth
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        record = session.scalar(select(Trial).where(Trial.tenant_id == principal.tenant_id))
        return None if record is None else {"starts_at": record.starts_at, "ends_at": record.ends_at}

    @router.post("/admin/tenants/{tenant_id}/suspend", status_code=status.HTTP_204_NO_CONTENT)
    def admin_suspend(tenant_id: UUID, auth=Depends(current_auth)):
        principal, _, session = auth
        if not principal.is_super_admin:
            raise HTTPException(status_code=403, detail="Super Admin required")
        try:
            suspend_tenant(session, tenant_id=tenant_id, actor=principal)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
