from pathlib import Path


INSTALL = Path(__file__).resolve().parents[1] / "install.sh"
COMPOSE = Path(__file__).resolve().parents[1] / "gateway" / "docker-compose.yml"


def _script() -> str:
    assert INSTALL.exists(), "install.sh must exist at repository root"
    return INSTALL.read_text(encoding="utf-8")


def _compose() -> str:
    assert COMPOSE.exists(), "gateway/docker-compose.yml must exist"
    return COMPOSE.read_text(encoding="utf-8")


def test_installer_is_strict_and_root_only():
    script = _script()
    assert "set -Eeuo pipefail" in script
    assert "EUID" in script


def test_installer_supports_ubuntu_and_installs_dependencies():
    script = _script()
    assert "/etc/os-release" in script
    assert "ubuntu" in script.lower()
    for token in ("ca-certificates", "curl", "git", "docker.io", "docker-compose-v2"):
        assert token in script


def test_installer_clones_feature_branch_to_opt():
    script = _script()
    assert "https://github.com/OpenSMSProject/RCS.git" in script
    assert "feature/remote-connector-v1" in script
    assert "/opt/opensms-rcs" in script


def test_installer_generates_tokens_without_overwriting_existing_env():
    script = _script()
    assert "openssl rand -hex 32" in script
    assert "OPENSMS_API_TOKEN" in script
    assert "OPENSMS_ADMIN_TOKEN" in script
    assert "if [[ ! -f \"$ENV_FILE\" ]]" in script
    assert "chmod 600 \"$ENV_FILE\"" in script


def test_installer_makes_persistent_data_writable_by_gateway_user():
    script = _script()
    assert "chown -R 10001:10001 \"$DATA_DIR\"" in script
    assert "chmod 700 \"$DATA_DIR\"" in script


def test_gateway_is_published_on_lan_port_8080():
    compose = _compose()
    assert '"0.0.0.0:8080:8080"' in compose


def test_installer_installs_rcs_management_command():
    script = _script()
    assert "/usr/local/bin/rcs" in script
    for token in ("update)", "status)", "restart)", "logs)"):
        assert token in script
    assert "git fetch origin \"$BRANCH\"" in script
    assert "git merge --ff-only \"origin/$BRANCH\"" in script
    assert "docker compose up -d --build" in script


def test_installer_starts_gateway_and_checks_health():
    script = _script()
    assert "docker compose up -d --build" in script
    assert "http://127.0.0.1:8080/healthz" in script
    assert "http://127.0.0.1:8080/readyz" in script
    assert "FINAL_STATUS=PASS" in script


def test_installer_reports_complete_final_status_only_after_validation():
    script = _script()
    required = (
        "RCS_BRANCH=",
        "RCS_COMMIT=",
        "DOCKER_STATUS=",
        "GATEWAY_CONTAINER_STATUS=",
        "HEALTHZ=PASS",
        "READYZ=PASS",
        "LOCAL_ACCESS=",
        "INSTALL_DIR=",
        "CREDENTIALS_FILE=",
        "TOKENS_PRINTED=NO",
        "FINAL_STATUS=PASS",
    )
    for token in required:
        assert token in script

    validation = script.index('if [[ "$health_ok" -ne 1 ]]')
    final_status = script.index("FINAL_STATUS=PASS")
    assert final_status > validation
