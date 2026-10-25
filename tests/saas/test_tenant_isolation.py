import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.models import Base, User
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


def signup(client, email, document):
    response = client.post("/saas/v1/signup", json={
        "email": email,
        "password": "password-123",
        "tenant_type": "PF",
        "document_number": document,
        "display_name": email,
    })
    assert response.status_code == 201
    return response.json()


def verify(factory, email):
    with factory.begin() as session:
        user = session.scalar(select(User).where(User.email == email))
        user.email_verified = True


def logged_in_client(client, factory, email, tenant_id):
    verify(factory, email)
    response = client.post("/saas/v1/login", json={"email": email, "password": "password-123", "tenant_id": tenant_id})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_tenant_b_cannot_list_or_release_tenant_a_devices():
    client_a, factory, gateway = make_app()
    gateway.create_device("dev-a", "Phone A", "secret")
    a = signup(client_a, "a@example.com", "12345678901")
    csrf_a = logged_in_client(client_a, factory, "a@example.com", a["tenant_id"])
    assert client_a.post("/saas/v1/devices/claim", json={"device_id": "dev-a"}, headers={"X-CSRF-Token": csrf_a}).status_code == 201

    client_b = TestClient(client_a.app)
    b = signup(client_b, "b@example.com", "98765432100")
    csrf_b = logged_in_client(client_b, factory, "b@example.com", b["tenant_id"])
    assert client_b.get("/saas/v1/devices").json() == {"devices": []}
    release = client_b.delete("/saas/v1/devices/dev-a", headers={"X-CSRF-Token": csrf_b})
    assert release.status_code == 404
    assert client_a.get("/saas/v1/devices").json()["devices"][0]["device_id"] == "dev-a"


def test_tenant_b_cannot_revoke_tenant_a_api_key_by_identifier():
    client_a, factory, _ = make_app()
    a = signup(client_a, "a@example.com", "12345678901")
    csrf_a = logged_in_client(client_a, factory, "a@example.com", a["tenant_id"])
    created = client_a.post("/saas/v1/api-keys", json={"label": "A"}, headers={"X-CSRF-Token": csrf_a}).json()

    client_b = TestClient(client_a.app)
    b = signup(client_b, "b@example.com", "98765432100")
    csrf_b = logged_in_client(client_b, factory, "b@example.com", b["tenant_id"])
    response = client_b.delete(f"/saas/v1/api-keys/{created['id']}", headers={"X-CSRF-Token": csrf_b})
    assert response.status_code == 404
    assert len(client_a.get("/saas/v1/api-keys").json()["api_keys"]) == 1
