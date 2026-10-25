import os
import sys

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.app import create_app
from opensms_gateway.config import GatewaySettings
from opensms_gateway.registry import ConnectionRegistry
from opensms_gateway.storage import GatewayStore


def legacy_settings():
    return GatewaySettings(db_path=":memory:", api_token="api", admin_token="admin")


def route_paths(app):
    return {getattr(route, "path", None) for route in app.routes}


def test_saas_disabled_preserves_legacy_route_surface(monkeypatch):
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "0")
    app = create_app(settings=legacy_settings(), store=GatewayStore(":memory:"), registry=ConnectionRegistry())
    paths = route_paths(app)
    assert "/healthz" in paths and "/readyz" in paths and "/api/v1/messages" in paths
    assert not any(path and path.startswith("/saas/v1") for path in paths)
    assert getattr(app.state, "saas_enabled", False) is False


def test_saas_enabled_mounts_router_without_changing_legacy_routes(monkeypatch):
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "1")
    monkeypatch.setenv("OPENSMS_SAAS_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("OPENSMS_SAAS_SESSION_SECRET", "x" * 48)
    monkeypatch.setenv("OPENSMS_SAAS_SECURE_COOKIES", "0")
    app = create_app(settings=legacy_settings(), store=GatewayStore(":memory:"), registry=ConnectionRegistry())
    paths = route_paths(app)
    assert "/api/v1/messages" in paths and "/api/v1/device/connect" in paths
    assert "/saas/v1/signup" in paths and "/saas/v1/login" in paths and "/saas/v1/me" in paths
    assert app.state.saas_enabled is True
    assert app.state.saas_engine is not None
