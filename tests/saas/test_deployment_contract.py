from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "gateway" / "docker-compose.yml"
DOCKERFILE = ROOT / "gateway" / "Dockerfile"
START = ROOT / "gateway" / "start.sh"
INSTALL = ROOT / "install.sh"
ENV_EXAMPLE = ROOT / "gateway" / ".env.example"


def text(path: Path) -> str:
    assert path.exists(), f"required deployment file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_postgres_16_is_private_persistent_and_health_checked():
    compose = text(COMPOSE)
    assert "opensms-postgres:" in compose
    assert "postgres:16-alpine" in compose
    assert "POSTGRES_DB" in compose and "POSTGRES_USER" in compose and "POSTGRES_PASSWORD" in compose
    assert "opensms-postgres-data:/var/lib/postgresql/data" in compose
    assert "pg_isready" in compose
    postgres_section = compose.split("opensms-postgres:", 1)[1].split("opensms-gateway:", 1)[0]
    assert "ports:" not in postgres_section, "PostgreSQL must not be published to the LAN"
    assert "opensms-postgres-data:" in compose.split("volumes:")[-1]


def test_gateway_waits_for_postgres_and_still_publishes_only_http_8080():
    compose = text(COMPOSE)
    gateway_section = compose.split("opensms-gateway:", 1)[1]
    assert "depends_on:" in gateway_section
    assert "opensms-postgres:" in gateway_section
    assert "condition: service_healthy" in gateway_section
    assert '"0.0.0.0:8080:8080"' in gateway_section


def test_container_runs_migrations_before_uvicorn():
    dockerfile = text(DOCKERFILE)
    start = text(START)
    assert "COPY start.sh" in dockerfile
    assert "start.sh" in dockerfile
    assert "alembic" in start
    assert "upgrade head" in start
    assert "uvicorn" in start
    assert start.index("upgrade head") < start.index("uvicorn")
    assert "OPENSMS_SAAS_ENABLED" in start


def test_installer_enables_saas_and_appends_missing_secrets_idempotently():
    script = text(INSTALL)
    for token in (
        "OPENSMS_SAAS_ENABLED",
        "OPENSMS_SAAS_DATABASE_URL",
        "OPENSMS_SAAS_SESSION_SECRET",
        "OPENSMS_POSTGRES_PASSWORD",
        "OPENSMS_SAAS_SECURE_COOKIES",
    ):
        assert token in script
    assert "ensure_env_var" in script
    assert "openssl rand -hex 32" in script
    assert "Preserving existing gateway credentials" in script
    assert "SAAS_STATUS=ENABLED" in script
    assert "SAAS_DATABASE=POSTGRESQL" in script


def test_env_example_documents_all_saas_runtime_variables():
    env = text(ENV_EXAMPLE)
    for token in (
        "OPENSMS_SAAS_ENABLED",
        "OPENSMS_SAAS_DATABASE_URL",
        "OPENSMS_SAAS_SESSION_SECRET",
        "OPENSMS_POSTGRES_PASSWORD",
        "OPENSMS_SAAS_SECURE_COOKIES",
    ):
        assert f"{token}=" in env


def test_installer_never_prints_generated_saas_secrets():
    script = text(INSTALL)
    final_block = script[script.index("OpenSMS/RCS FINAL STATUS") :]
    assert "OPENSMS_POSTGRES_PASSWORD" not in final_block
    assert "OPENSMS_SAAS_SESSION_SECRET" not in final_block
    assert "OPENSMS_API_TOKEN" not in final_block
    assert "OPENSMS_ADMIN_TOKEN" not in final_block
