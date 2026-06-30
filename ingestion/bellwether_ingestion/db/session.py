"""Async engine + session factory.

DATABASE_URL may be a plain `postgresql://...` DSN; we coerce it to the asyncpg
driver for the application engine. Alembic migrations use a sync driver (see
migrate.py).
"""

from __future__ import annotations

import os
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DSN = os.environ.get(
    "DATABASE_URL", "postgresql://bellwether:bellwether@localhost:5432/bellwether"
)


def async_dsn(url: Optional[str] = None) -> str:
    url = url or DEFAULT_DSN
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


def sync_dsn(url: Optional[str] = None) -> str:
    """Sync (psycopg2) DSN for Alembic migrations."""
    url = url or DEFAULT_DSN
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix) :]
    return url


def make_engine(url: Optional[str] = None, **kwargs) -> AsyncEngine:
    return create_async_engine(async_dsn(url), **kwargs)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
