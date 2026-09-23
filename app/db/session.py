"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.core.errors import DatabaseUnavailable

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _connect_args(database_url: str) -> dict:
    """Disable asyncpg's prepared-statement cache on the transaction pooler."""
    parsed = urlparse(database_url)
    if parsed.port == 6543:
        return {"statement_cache_size": 0}
    return {}


def get_engine() -> AsyncEngine:
    """Lazily create the process-wide async engine.

    Raises DatabaseUnavailable if DATABASE_URL is missing so /health can
    return 503 instead of crashing at import time.
    """
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if not url:
            raise DatabaseUnavailable("DATABASE_URL is not set")
        _engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            connect_args=_connect_args(url),
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared sessionmaker, creating it on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a request-scoped session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def dispose_engine() -> None:
    """Close the connection pool on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
