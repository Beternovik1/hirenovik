"""SQLAlchemy engine and session factory for the API layer.

Wraps :func:`src.database.models.db_connect` with an API-friendly
session factory and a ``get_db`` dependency that FastAPI routers use
via ``Depends(get_db)``. The engine is created lazily so importing this
module never touches the database.
"""

import logging
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.api.config import get_settings

logger = logging.getLogger(__name__)

#: Module-level engine, initialised lazily on first access.
_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """Return a lazily-created SQLAlchemy engine.

    The engine is created once and cached so connection pooling is shared
    across requests. The Supabase ``postgres://`` scheme is normalised to
    ``postgresql://`` for SQLAlchemy 2.x compatibility.

    Returns:
        A SQLAlchemy engine bound to ``DATABASE_URL``.
    """
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = settings.database_url.replace("postgres://", "postgresql://")
    logger.info("Creating database engine for %s", url.split("@")[-1])
    _engine = create_engine(
        url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )
    return _engine


def get_session_factory() -> sessionmaker:
    """Return a cached sessionmaker bound to the engine."""
    global _session_factory
    if _session_factory is not None:
        return _session_factory
    _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and closes it on exit."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    """Drop the cached engine and session factory (used in tests)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None