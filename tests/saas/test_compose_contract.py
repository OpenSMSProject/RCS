from pathlib import Path


def test_compose_adds_internal_persistent_postgres_without_host_port():
    text = Path("gateway/docker-compose.yml").read_text()
    assert "opensms-postgres:" in text
    assert "postgres:16" in text
    assert "opensms-postgres-data:" in text
    postgres_block = text.split("opensms-postgres:", 1)[1].split("volumes:", 1)[0]
    assert "ports:" not in postgres_block
    assert "condition: service_healthy" in text
    assert '"0.0.0.0:8080:8080"' in text


def test_installer_preserves_existing_env_and_generates_missing_saas_secrets():
    text = Path("install.sh").read_text()
    assert "Preserving existing gateway credentials" in text
    assert "OPENSMS_POSTGRES_PASSWORD" in text
    assert "OPENSMS_SAAS_SESSION_SECRET" in text
    assert "openssl rand" in text
    assert "TOKENS_PRINTED=NO" in text
    assert 'chown -R 10001:10001 "$DATA_DIR"' in text
    assert 'chmod 700 "$DATA_DIR"' in text


def test_install_and_update_run_migrations_before_readiness():
    text = Path("install.sh").read_text()
    assert "alembic" in text
    assert "upgrade head" in text
    assert "run_saas_migrations" in text
    update_section = text.split("update)", 1)[1].split("status)", 1)[0]
    assert update_section.index("run_saas_migrations") < update_section.index("wait_health")
    assert "FINAL_STATUS=PASS" in text


def test_env_example_documents_saas_and_postgres_without_real_secrets():
    text = Path("gateway/.env.example").read_text()
    assert "OPENSMS_SAAS_ENABLED" in text
    assert "OPENSMS_POSTGRES_PASSWORD" in text
    assert "OPENSMS_SAAS_DATABASE_URL" in text
    assert "replace-with" in text or "change-me" in text
