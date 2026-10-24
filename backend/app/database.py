"""Database engine and session management for application and target databases."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for application models."""
    pass


# ---------------------------------------------------------------------------
# Application database (read-write, for internal persistence)
# ---------------------------------------------------------------------------

_app_engine = None
_AppSessionLocal = None


def get_app_engine():
    """Get or create the application database engine."""
    global _app_engine
    if _app_engine is None:
        settings = get_settings()
        _app_engine = create_engine(
            settings.app_database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=settings.is_development,
        )
    return _app_engine


def get_app_session_factory():
    """Get or create the application session factory."""
    global _AppSessionLocal
    if _AppSessionLocal is None:
        _AppSessionLocal = sessionmaker(
            bind=get_app_engine(),
            autocommit=False,
            autoflush=False,
        )
    return _AppSessionLocal


def get_app_db() -> Session:
    """Yield an application database session (dependency injection)."""
    factory = get_app_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Target database (read-only, restricted, for analytics queries)
# ---------------------------------------------------------------------------

def create_target_engine(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
    statement_timeout_ms: int = 30000,
):
    """Create a restricted, read-only engine for target database queries.

    Uses a dedicated least-privilege role. Enforces statement timeout
    and read-only transaction mode at the connection level.
    """
    url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"
    engine = create_engine(
        url,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
        echo=False,
        # Set connection-level defaults
        connect_args={
            "options": f"-c statement_timeout={statement_timeout_ms} -c default_transaction_read_only=on",
        },
    )
    return engine


def get_default_target_engine():
    """Create a target engine using default settings."""
    settings = get_settings()
    return create_target_engine(
        host=settings.target_db_host,
        port=settings.target_db_port,
        dbname=settings.target_db_name,
        user=settings.target_db_user,
        password=settings.target_db_password,
        statement_timeout_ms=settings.sql_statement_timeout_ms,
    )


def init_app_db():
    """Initialize the application database tables."""
    import app.models  # noqa: F401 - ensure models are registered
    engine = get_app_engine()
    Base.metadata.create_all(bind=engine)


def check_db_health(engine) -> dict:
    """Check database connectivity and return status info."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        return {"status": "healthy", "error": None}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
