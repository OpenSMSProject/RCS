import os
import subprocess

import pytest
from sqlalchemy import create_engine, inspect, text


def _database_url():
    value = os.environ.get("OPENSMS_SAAS_DATABASE_URL", "").strip()
    if not value or value.startswith("sqlite"):
        pytest.skip("PostgreSQL integration database not configured")
    return value


def test_postgres_migration_is_repeatable_and_database_ready():
    from gateway.opensms_gateway.saas.db import database_ready

    url = _database_url()
    env = dict(os.environ)
    env["OPENSMS_SAAS_DATABASE_URL"] = url
    command = ["alembic", "-c", "gateway/opensms_gateway/saas/migrations/alembic.ini", "upgrade", "head"]
    subprocess.check_call(command, env=env)
    subprocess.check_call(command, env=env)
    engine = create_engine(url, pool_pre_ping=True)
    assert database_ready(engine) is True
    tables = set(inspect(engine).get_table_names())
    assert {"tenants", "users", "memberships", "plans", "trials", "api_keys", "tenant_devices", "audit_events"}.issubset(tables)


def test_postgres_unavailable_readiness_is_false_without_touching_sqlite(tmp_path):
    from gateway.opensms_gateway.saas.db import database_ready
    from gateway.opensms_gateway.storage import GatewayStore

    sqlite_path = tmp_path / "legacy.sqlite3"
    store = GatewayStore(str(sqlite_path))
    store.create_device("legacy-device", "Phone", "credential")
    before = sqlite_path.read_bytes()

    class BrokenEngine:
        def connect(self):
            raise RuntimeError("down")

    assert database_ready(BrokenEngine()) is False
    assert sqlite_path.read_bytes() == before
    assert store.get_device("legacy-device")["device_id"] == "legacy-device"
