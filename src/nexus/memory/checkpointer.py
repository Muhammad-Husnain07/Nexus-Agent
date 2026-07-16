"""Persistent LangGraph checkpointer via PostgresSaver.

Provides a singleton ``PostgresSaver`` bound to the application's async
SQLAlchemy engine.  Used by the compiled agent graph to persist checkpoint
state across process restarts (enables resume + HITL + time-travel).
"""

from __future__ import annotations

import structlog
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg_pool import AsyncConnectionPool

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.memory.checkpointer")

_checkpointer: PostgresSaver | None = None


def create_pool() -> AsyncConnectionPool:
    """Create an ``AsyncConnectionPool`` from the application's database URL.

    The pool uses the same connection string as the SQLAlchemy engine but
    replaces the ``+asyncpg`` driver suffix with the raw PostgreSQL scheme
    that psycopg expects.
    """
    settings = get_settings()
    raw_url = settings.database.url
    # psycopg needs postgres:// not postgresql+asyncpg://
    pg_url = raw_url.replace("postgresql+asyncpg://", "postgresql://")
    return AsyncConnectionPool(pg_url, min_size=1, max_size=5)


async def get_checkpointer() -> PostgresSaver:
    """Return a singleton ``PostgresSaver`` connected via an async pool.

    The first call creates the pool, connects the saver, runs ``setup()``
    to ensure checkpoint tables exist, and caches the instance.
    """
    global _checkpointer  # noqa: PLW0603

    if _checkpointer is not None:
        return _checkpointer

    pool = create_pool()
    conn: Connection = await pool.connection()
    saver = PostgresSaver(conn=conn)
    await saver.setup()
    _checkpointer = saver
    logger.info("checkpointer.initialized")
    return _checkpointer


def get_sync_checkpointer() -> PostgresSaver | None:
    """Return the cached checkpointer if already initialised."""
    return _checkpointer


async def close_checkpointer() -> None:
    """Close the underlying connection pool."""
    global _checkpointer  # noqa: PLW0603

    if _checkpointer is not None:
        pool = _checkpointer.conn.pool  # type: ignore[union-attr]
        if pool is not None:
            await pool.close()
        _checkpointer = None
        logger.info("checkpointer.closed")
