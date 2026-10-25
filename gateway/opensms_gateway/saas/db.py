from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .config import SaaSSettings


def create_engine_from_settings(settings: SaaSSettings) -> Engine:
    if not settings.enabled or not settings.database_url:
        raise ValueError("SaaS database is not configured")
    return create_engine(settings.database_url, pool_pre_ping=True)


def session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def database_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1
    except Exception:
        return False
