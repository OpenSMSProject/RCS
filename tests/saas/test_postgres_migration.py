import os
import sys

from sqlalchemy import create_engine, inspect

sys.path.insert(0, os.path.abspath("gateway"))


def _unique_column_sets(inspector, table_name: str) -> set[tuple[str, ...]]:
    constraints = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints(table_name)
    }
    indexes = {
        tuple(item["column_names"])
        for item in inspector.get_indexes(table_name)
        if item.get("unique")
    }
    return constraints | indexes


def test_real_postgres_has_phase1_schema_after_alembic_upgrade():
    url = os.environ.get("OPENSMS_SAAS_DATABASE_URL", "").strip()
    assert url, "CI must provide OPENSMS_SAAS_DATABASE_URL backed by PostgreSQL 16"
    assert url.startswith("postgresql+psycopg://")
    engine = create_engine(url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "alembic_version", "tenants", "users", "memberships", "plans",
        "tenant_entitlements", "trials", "api_keys", "tenant_devices",
        "audit_events", "session_records", "email_verification_tokens",
    } <= tables
    assert ("document_number",) in _unique_column_sets(inspector, "tenants")
    assert ("tenant_id", "user_id") in _unique_column_sets(inspector, "memberships")
