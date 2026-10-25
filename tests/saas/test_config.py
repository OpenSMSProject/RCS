import pytest


def test_saas_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OPENSMS_SAAS_ENABLED", raising=False)
    monkeypatch.delenv("OPENSMS_SAAS_DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENSMS_SAAS_SESSION_SECRET", raising=False)

    from gateway.opensms_gateway.saas.config import SaaSSettings

    settings = SaaSSettings.from_env()
    assert settings.enabled is False
    assert settings.database_url is None


def test_enabled_saas_requires_database_url(monkeypatch):
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "1")
    monkeypatch.delenv("OPENSMS_SAAS_DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENSMS_SAAS_SESSION_SECRET", "x" * 32)

    from gateway.opensms_gateway.saas.config import SaaSSettings

    with pytest.raises(ValueError, match="OPENSMS_SAAS_DATABASE_URL"):
        SaaSSettings.from_env()


def test_enabled_saas_requires_strong_session_secret(monkeypatch):
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "1")
    monkeypatch.setenv("OPENSMS_SAAS_DATABASE_URL", "postgresql+psycopg://user:pass@db/opensms")
    monkeypatch.setenv("OPENSMS_SAAS_SESSION_SECRET", "short")

    from gateway.opensms_gateway.saas.config import SaaSSettings

    with pytest.raises(ValueError, match="OPENSMS_SAAS_SESSION_SECRET"):
        SaaSSettings.from_env()


def test_enabled_saas_parses_valid_settings(monkeypatch):
    monkeypatch.setenv("OPENSMS_SAAS_ENABLED", "true")
    monkeypatch.setenv("OPENSMS_SAAS_DATABASE_URL", "postgresql+psycopg://user:pass@db/opensms")
    monkeypatch.setenv("OPENSMS_SAAS_SESSION_SECRET", "s" * 32)

    from gateway.opensms_gateway.saas.config import SaaSSettings

    settings = SaaSSettings.from_env()
    assert settings.enabled is True
    assert settings.database_url.endswith("/opensms")
    assert settings.session_secret == "s" * 32
