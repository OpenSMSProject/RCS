from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api_keys import create_api_key, revoke_api_key
from .auth import Principal, authenticate_session
from .devices import claim_existing_device, list_tenant_devices, release_device
from .entitlements import evaluate_entitlement
from .models import ApiKey, Membership, SessionRecord, Tenant, TenantRole, TenantType, Trial, User
from .security import hash_session_token, new_session_token, verify_password
from .tenants import provision_trial_tenant


SESSION_COOKIE = "opensms_session"


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=256)
    tenant_type: TenantType
    document_number: str
    display_name: str


class LoginRequest(BaseModel):
    email: str
    password: str
    tenant_id: Optional[UUID] = None


class ApiKeyCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)


class DeviceClaimRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)


def build_saas_router(session_factory, gateway_store, *, secure_cookies: bool = True) -> APIRouter:
    router = APIRouter(tags=["saas"])

    def db_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def principal_from_request(
        request: Request,
        session: Session = Depends(db_session),
    ) -> Principal:
        raw = request.cookies.get(SESSION_COOKIE)
        if not raw:
            raise HTTPException(status_code=401, detail="authentication required")
        return authenticate_session(session, raw)

    def require_csrf(
        request: Request,
        csrf_token: Optional[str] = Header(default=None, alias="X-CSRF-Token"),
        session: Session = Depends(db_session),
    ) -> None:
        raw_session = request.cookies.get(SESSION_COOKIE)
        if not raw_session or not csrf_token:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        record = session.scalar(
            select(SessionRecord).where(SessionRecord.token_hash == hash_session_token(raw_session))
        )
        if record is None or record.revoked_at is not None or not record.csrf_token_hash:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        if record.csrf_token_hash != hash_session_token(csrf_token):
            raise HTTPException(status_code=403, detail="CSRF validation failed")

    @router.post("/signup", status_code=status.HTTP_201_CREATED)
    def signup(payload: SignupRequest, session: Session = Depends(db_session)):
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
            session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "tenant_id": str(tenant.id),
            "tenant_type": tenant.tenant_type.value,
            "email_verification_required": True,
        }

    @router.post("/login")
    def login(payload: LoginRequest, response: Response, session: Session = Depends(db_session)):
        email = payload.email.strip().lower()
        user = session.scalar(select(User).where(User.email == email))
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        if not user.email_verified:
            raise HTTPException(status_code=403, detail="email verification required")

        tenant_id = payload.tenant_id
        if user.is_super_admin and tenant_id is None:
            selected_tenant_id = None
        else:
            memberships = list(session.scalars(select(Membership).where(Membership.user_id == user.id)).all())
            if tenant_id is None:
                if len(memberships) != 1:
                    raise HTTPException(status_code=409, detail="tenant selection required")
                selected_tenant_id = memberships[0].tenant_id
            else:
                membership = next((m for m in memberships if m.tenant_id == tenant_id), None)
                if membership is None:
                    raise HTTPException(status_code=403, detail="forbidden")
                selected_tenant_id = tenant_id

        raw_session = new_session_token()
        raw_csrf = new_session_token()
        record = SessionRecord(
            user_id=user.id,
            tenant_id=selected_tenant_id,
            token_hash=hash_session_token(raw_session),
            csrf_token_hash=hash_session_token(raw_csrf),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
        )
        session.add(record)
        session.commit()
        response.set_cookie(
            SESSION_COOKIE,
            raw_session,
            httponly=True,
            secure=secure_cookies,
            samesite="strict",
            max_age=12 * 60 * 60,
            path="/",
        )
        return {"csrf_token": raw_csrf, "tenant_id": str(selected_tenant_id) if selected_tenant_id else None}

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
    def logout(request: Request, response: Response, session: Session = Depends(db_session)):
        raw = request.cookies.get(SESSION_COOKIE)
        record = session.scalar(select(SessionRecord).where(SessionRecord.token_hash == hash_session_token(raw)))
        if record is not None:
            record.revoked_at = datetime.now(timezone.utc)
            session.commit()
        response.delete_cookie(SESSION_COOKIE, path="/")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/me")
    def me(principal: Principal = Depends(principal_from_request)):
        return {
            "user_id": str(principal.user_id) if principal.user_id else None,
            "tenant_id": str(principal.tenant_id) if principal.tenant_id else None,
            "role": principal.role.value if principal.role else None,
            "is_super_admin": principal.is_super_admin,
        }

    @router.get("/api-keys")
    def list_api_keys(
        principal: Principal = Depends(principal_from_request),
        session: Session = Depends(db_session),
    ):
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        rows = session.scalars(
            select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id).order_by(ApiKey.created_at, ApiKey.id)
        ).all()
        return {"api_keys": [
            {
                "id": str(row.id), "label": row.label, "key_prefix": row.key_prefix,
                "created_at": row.created_at.isoformat(),
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            }
            for row in rows
        ]}

    @router.post("/api-keys", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
    def make_api_key(
        payload: ApiKeyCreateRequest,
        principal: Principal = Depends(principal_from_request),
        session: Session = Depends(db_session),
    ):
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        try:
            record, raw = create_api_key(
                session, tenant_id=principal.tenant_id, actor=principal, label=payload.label
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"id": str(record.id), "label": record.label, "key_prefix": record.key_prefix, "api_key": raw}

    @router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
    def delete_api_key(
        key_id: UUID,
        principal: Principal = Depends(principal_from_request),
        session: Session = Depends(db_session),
    ):
        try:
            revoke_api_key(session, key_id=key_id, actor=principal)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="API key not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/devices")
    def devices(
        principal: Principal = Depends(principal_from_request),
        session: Session = Depends(db_session),
    ):
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        try:
            rows = list_tenant_devices(session, tenant_id=principal.tenant_id, actor=principal)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"devices": [
            {"id": str(row.id), "device_id": row.device_id, "claimed_at": row.claimed_at.isoformat()}
            for row in rows
        ]}

    @router.post("/devices/claim", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
    def claim_device(
        payload: DeviceClaimRequest,
        principal: Principal = Depends(principal_from_request),
        session: Session = Depends(db_session),
    ):
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        try:
            mapping = claim_existing_device(
                session,
                tenant_id=principal.tenant_id,
                device_id=payload.device_id,
                actor=principal,
                gateway_store=gateway_store,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="device not available") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"id": str(mapping.id), "device_id": mapping.device_id}

    @router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
    def unclaim_device(
        device_id: str,
        principal: Principal = Depends(principal_from_request),
        session: Session = Depends(db_session),
    ):
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        try:
            release_device(
                session, tenant_id=principal.tenant_id, device_id=device_id, actor=principal
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="device not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/entitlements")
    def entitlements(
        principal: Principal = Depends(principal_from_request),
        session: Session = Depends(db_session),
    ):
        if principal.tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant context required")
        now = datetime.now(timezone.utc)
        values = {}
        for capability in ("users", "devices", "api_keys", "external_api", "bulk_campaigns"):
            decision = evaluate_entitlement(session, tenant_id=principal.tenant_id, capability=capability, now=now)
            values[capability] = {
                "allowed": decision.allowed,
                "reason": decision.reason,
                "limit": decision.limit,
                "used": decision.used,
            }
        trial = session.scalar(select(Trial).where(Trial.tenant_id == principal.tenant_id))
        return {"entitlements": values, "trial_expires_at": trial.expires_at.isoformat() if trial else None}

    return router
