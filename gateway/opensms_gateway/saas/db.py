from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .config import SaaSSettings


def create_engine_from_settings(settings: SaaSSettings) -> Engine:
    if not settings.enabled or not settings.database_url:
        raise ValueError("SaaS database is not enabled/configured")
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def session_factory(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def database_ready(engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
