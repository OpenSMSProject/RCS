import pytest


def test_session_factory_commits_and_rolls_back():
    from sqlalchemy import text
    from gateway.opensms_gateway.saas.config import SaaSSettings
    from gateway.opensms_gateway.saas.db import create_engine_from_settings, session_factory

    settings = SaaSSettings(enabled=True, database_url="sqlite+pysqlite:///:memory:", session_secret="s" * 32)
    engine = create_engine_from_settings(settings)
    engine.execute if False else None
    with engine.begin() as conn:
        conn.execute(text("create table sample (id integer primary key, value text)"))

    factory = session_factory(engine)
    with factory.begin() as session:
        session.execute(text("insert into sample(value) values ('ok')"))

    with factory() as session:
        assert session.execute(text("select count(*) from sample")).scalar_one() == 1

    session = factory()
    try:
        session.execute(text("insert into sample(value) values ('rollback')"))
        session.rollback()
    finally:
        session.close()

    with factory() as session:
        assert session.execute(text("select count(*) from sample")).scalar_one() == 1


def test_database_ready_false_on_connection_failure():
    from gateway.opensms_gateway.saas.db import database_ready

    class BrokenEngine:
        def connect(self):
            raise RuntimeError("database unavailable")

    assert database_ready(BrokenEngine()) is False


def test_database_ready_true_for_live_engine():
    from gateway.opensms_gateway.saas.config import SaaSSettings
    from gateway.opensms_gateway.saas.db import create_engine_from_settings, database_ready

    settings = SaaSSettings(enabled=True, database_url="sqlite+pysqlite:///:memory:", session_secret="s" * 32)
    engine = create_engine_from_settings(settings)
    assert database_ready(engine) is True


def test_engine_creation_rejects_disabled_or_missing_database_url():
    from gateway.opensms_gateway.saas.config import SaaSSettings
    from gateway.opensms_gateway.saas.db import create_engine_from_settings

    with pytest.raises(ValueError):
        create_engine_from_settings(SaaSSettings(enabled=False, database_url=None, session_secret=None))
