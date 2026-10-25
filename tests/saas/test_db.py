import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.abspath("gateway"))

from opensms_gateway.saas.config import SaaSSettings
from opensms_gateway.saas.db import create_engine_from_settings, database_ready, session_factory


def test_session_factory_commits_and_rolls_back():
    settings = SaaSSettings(enabled=True, database_url="sqlite+pysqlite:///:memory:", session_secret="x" * 48)
    engine = create_engine_from_settings(settings)
    factory = session_factory(engine)
    with engine.begin() as conn:
        conn.execute(text("create table sample (id integer primary key, value text)"))
    with factory.begin() as session:
        session.execute(text("insert into sample(value) values ('ok')"))
    with factory() as session:
        assert session.execute(text("select count(*) from sample")).scalar_one() == 1
    try:
        with factory.begin() as session:
            session.execute(text("insert into sample(value) values ('rollback')"))
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass
    with factory() as session:
        assert session.execute(text("select count(*) from sample")).scalar_one() == 1


def test_database_ready_false_on_connection_failure():
    settings = SaaSSettings(enabled=True, database_url="sqlite+pysqlite:////no/such/directory/opensms.db", session_secret="x" * 48)
    engine = create_engine_from_settings(settings)
    assert database_ready(engine) is False


def test_database_ready_true_for_live_engine():
    settings = SaaSSettings(enabled=True, database_url="sqlite+pysqlite:///:memory:", session_secret="x" * 48)
    engine = create_engine_from_settings(settings)
    assert database_ready(engine) is True
