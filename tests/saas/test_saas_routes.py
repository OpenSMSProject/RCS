import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.models import Base, Membership, User
from opensms_gateway.saas.routes import build_saas_router
from opensms_gateway.storage import GatewayStore


def make_app():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    gateway = GatewayStore(":memory:")
    app = FastAPI()
    app.include_router(build_saas_router(factory, gateway, secure_cookies=False), prefix="/saas/v1")
    return TestClient(app), factory, gateway


def signup(client, *, email="owner@example.com", document="12345678901", tenant_type="PF"):
    response = client.post("/saas/v1/signup", json={
        "email": email,
        "password": "password-123",
        "tenant_type": tenant_type,
        "document_number": document,
        "display_name": email,
    })
    assert response.status_code == 201, response.text
    return response.json()


def verify_user(factory, email):
    with factory.begin() as session:
        user = session.scalar(select(User).where(User.email == email))
        user.email_verified = True


def login(client, *, email="owner@example.com", tenant_id=None):
    payload = {"email": email, "password": "password-123"}
    if tenant_id:
        payload["tenant_id"] = tenant_id
    response = client.post("/saas/v1/login", json=payload)
    assert response.status_code == 200, response.text
    return response


def test_signup_login_session_cookie_me_and_logout_csrf():
    client, factory, _ = make_app()
    created = signup(client)
    assert created["tenant_type"] == "PF" and created["email_verification_required"] is True
    denied = client.post("/saas/v1/login", json={"email": "owner@example.com", "password": "password-123"})
    assert denied.status_code == 403
    verify_user(factory, "owner@example.com")
    response = login(client, tenant_id=created["tenant_id"])
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    csrf = response.json()["csrf_token"]
    me = client.get("/saas/v1/me")
    assert me.status_code == 200
    assert me.json()["tenant_id"] == created["tenant_id"]
    assert me.json()["role"] == "Owner"
    assert client.post("/saas/v1/logout").status_code == 403
    logged_out = client.post("/saas/v1/logout", headers={"X-CSRF-Token": csrf})
    assert logged_out.status_code == 204
    assert client.get("/saas/v1/me").status_code == 401


def test_state_changes_require_csrf_and_api_key_raw_value_is_one_time():
    client, factory, _ = make_app()
    created = signup(client)
    verify_user(factory, "owner@example.com")
    csrf = login(client, tenant_id=created["tenant_id"]).json()["csrf_token"]
    assert client.post("/saas/v1/api-keys", json={"label": "ERP"}).status_code == 403
    made = client.post("/saas/v1/api-keys", json={"label": "ERP"}, headers={"X-CSRF-Token": csrf})
    assert made.status_code == 201
    body = made.json()
    assert body["api_key"].startswith("osms_live_")
    listed = client.get("/saas/v1/api-keys")
    assert listed.status_code == 200
    assert "api_key" not in listed.text and body["api_key"] not in listed.text


def test_device_claim_uses_legacy_gateway_without_mutating_it():
    client, factory, gateway = make_app()
    gateway.create_device("dev-1", "Phone", "device-secret")
    before = gateway.get_device("dev-1")
    created = signup(client)
    verify_user(factory, "owner@example.com")
    csrf = login(client, tenant_id=created["tenant_id"]).json()["csrf_token"]
    claim = client.post("/saas/v1/devices/claim", json={"device_id": "dev-1"}, headers={"X-CSRF-Token": csrf})
    assert claim.status_code == 201
    assert client.get("/saas/v1/devices").json()["devices"][0]["device_id"] == "dev-1"
    assert gateway.get_device("dev-1") == before
