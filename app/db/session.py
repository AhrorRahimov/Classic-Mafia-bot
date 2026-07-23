"""Async database engine, session factory and initialization."""
from __future__ import annotations

import logging
from typing import AsyncIterator

from sqlalchemy import text as sqlalchemy_text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.db.models import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazily create and cache the global async engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Lazily create and cache the global session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def init_db() -> None:
    """Create all tables and run lightweight in-place migrations.

    Safe to call on every startup. Existing SQLite databases get an
    ``ALTER TABLE`` to add new columns with sane defaults.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)


async def _migrate(conn: AsyncConnection) -> None:
    """Apply backward-compatible column additions for older databases."""
    await _ensure_column(conn, "user_stats", "language", "VARCHAR(8) DEFAULT 'ru'")


async def _ensure_column(
    conn: AsyncConnection, table: str, column: str, ddl_type: str
) -> None:
    """Add ``column`` to ``table`` if it does not already exist.

    Works for SQLite and PostgreSQL: we probe ``information_schema`` for
    PG and ``PRAGMA table_info`` for SQLite.
    """
    if conn.dialect.name == "sqlite":
        existing = await conn.execute(
            sqlalchemy_text(f"PRAGMA table_info({table})")
        )
        columns = {row[1] for row in existing.fetchall()}
    else:
        existing = await conn.execute(
            sqlalchemy_text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t"
            ),
            {"t": table},
        )
        columns = {row[0] for row in existing.fetchall()}
    if column not in columns:
        await conn.execute(
            sqlalchemy_text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
        )


async def dispose_db() -> None:
    """Dispose engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide a transactional DB session to handlers via middleware."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
