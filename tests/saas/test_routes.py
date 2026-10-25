from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def _stack():
    from gateway.opensms_gateway.saas.models import Base, Membership, User
    from gateway.opensms_gateway.saas.routes import build_saas_router
    from gateway.opensms_gateway.storage import GatewayStore

    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = GatewayStore(":memory:")
    app = FastAPI()
    app.include_router(build_saas_router(factory, store))
    return TestClient(app), factory, store


def _signup(client, email="owner@example.com", document="123.456.789-01"):
    response = client.post("/saas/v1/signup", json={"email": email, "password": "strong password", "tenant_type": "PF", "document_number": document, "display_name": "Tenant"})
    assert response.status_code == 201
    return response.json()


def _verify_user(factory, email="owner@example.com"):
    from gateway.opensms_gateway.saas.models import User
    with factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        user.email_verified = True
        session.commit()


def _login(client, email="owner@example.com"):
    response = client.post("/saas/v1/login", json={"email": email, "password": "strong password"})
    assert response.status_code == 200
    return response.json()["session_token"]


def test_signup_login_verification_gate_and_profile():
    client, factory, _ = _stack()
    _signup(client)
    assert client.post("/saas/v1/login", json={"email":"owner@example.com","password":"strong password"}).status_code == 403
    _verify_user(factory)
    token = _login(client)
    profile = client.get("/saas/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.status_code == 200
    assert profile.json()["role"] == "Owner"
    assert "password_hash" not in profile.text
    assert client.post("/saas/v1/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 204
    assert client.get("/saas/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_api_key_raw_secret_is_only_in_create_response():
    client, factory, _ = _stack()
    _signup(client); _verify_user(factory); token = _login(client)
    created = client.post("/saas/v1/api-keys", json={"label":"integration"}, headers={"Authorization": f"Bearer {token}"})
    assert created.status_code == 201
    assert created.json()["api_key"].startswith("osms_live_")
    listed = client.get("/saas/v1/api-keys", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert "osms_live_" not in listed.text
    assert "key_hash" not in listed.text


def test_tenant_device_claim_is_scoped():
    client, factory, store = _stack()
    _signup(client); _verify_user(factory); token = _login(client)
    store.create_device("device-1", "Phone", "credential")
    claimed = client.post("/saas/v1/devices/device-1/claim", headers={"Authorization": f"Bearer {token}"})
    assert claimed.status_code == 201
    devices = client.get("/saas/v1/devices", headers={"Authorization": f"Bearer {token}"})
    assert devices.status_code == 200
    assert devices.json()[0]["device_id"] == "device-1"
    assert "credential" not in devices.text


def test_super_admin_route_is_separate_from_tenant_owner():
    client, factory, _ = _stack()
    data = _signup(client); _verify_user(factory); token = _login(client)
    assert client.post(f"/saas/v1/admin/tenants/{data['tenant_id']}/suspend", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_legacy_app_does_not_mount_saas_when_disabled(monkeypatch):
    from gateway.opensms_gateway.app import create_app
    from gateway.opensms_gateway.config import GatewaySettings

    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "0")
    settings = GatewaySettings(db_path=":memory:", api_token="a", admin_token="b")
    client = TestClient(create_app(settings=settings))
    assert client.get("/healthz").status_code == 200
    assert client.get("/saas/v1/me").status_code == 404
