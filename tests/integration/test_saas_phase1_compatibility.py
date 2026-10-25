import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.app import create_app
from opensms_gateway.config import GatewaySettings
from opensms_gateway.registry import ConnectionRegistry
from opensms_gateway.storage import GatewayStore


def settings():
    return GatewaySettings(db_path=":memory:", api_token="api-token", admin_token="admin-token")


def test_saas_disabled_keeps_legacy_gateway_ready_and_routes_working(monkeypatch):
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "0")
    store = GatewayStore(":memory:")
    store.create_device("dev-legacy", "Legacy Phone", "secret")
    app = create_app(settings=settings(), store=store, registry=ConnectionRegistry())
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    devices = client.get("/api/v1/devices", headers={"Authorization": "Bearer admin-token"})
    assert devices.status_code == 200
    assert devices.json()["devices"][0]["device_id"] == "dev-legacy"
    assert client.get("/saas/v1/me").status_code == 404


def test_saas_database_outage_degrades_ready_without_corrupting_legacy_sqlite(monkeypatch):
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "1")
    monkeypatch.setenv("OPENSMS_SAAS_DATABASE_URL", "sqlite+pysqlite:////no/such/directory/opensms-saas.db")
    monkeypatch.setenv("OPENSMS_SAAS_SESSION_SECRET", "x" * 48)
    monkeypatch.setenv("OPENSMS_SAAS_SECURE_COOKIES", "0")

    store = GatewayStore(":memory:")
    store.create_device("dev-legacy", "Legacy Phone", "secret")
    before = store.get_device("dev-legacy")
    app = create_app(settings=settings(), store=store, registry=ConnectionRegistry())
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 503
    assert ready.json()["detail"] == "saas storage unavailable"
    devices = client.get("/api/v1/devices", headers={"Authorization": "Bearer admin-token"})
    assert devices.status_code == 200
    assert store.get_device("dev-legacy") == before
    assert client.get("/saas/v1/me").status_code == 401


def test_saas_enabled_does_not_change_legacy_message_contract(monkeypatch):
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "1")
    monkeypatch.setenv("OPENSMS_SAAS_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("OPENSMS_SAAS_SESSION_SECRET", "x" * 48)
    monkeypatch.setenv("OPENSMS_SAAS_SECURE_COOKIES", "0")

    store = GatewayStore(":memory:")
    store.create_device("dev-legacy", "Legacy Phone", "secret")
    app = create_app(settings=settings(), store=store, registry=ConnectionRegistry())
    client = TestClient(app)

    response = client.post(
        "/api/v1/messages",
        headers={"Authorization": "Bearer api-token", "Idempotency-Key": "compat-1"},
        json={"device_id": "dev-legacy", "to": "+5511999999999", "text": "compat"},
    )
    assert response.status_code == 202
    assert response.json()["state"] == "waiting_device"
    repeated = client.post(
        "/api/v1/messages",
        headers={"Authorization": "Bearer api-token", "Idempotency-Key": "compat-1"},
        json={"device_id": "dev-legacy", "to": "+5511999999999", "text": "compat"},
    )
    assert repeated.status_code == 202
    assert repeated.json()["message_id"] == response.json()["message_id"]
