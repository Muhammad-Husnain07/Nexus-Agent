"""Persistent LangGraph checkpointer via AsyncPostgresSaver.

Provides a singleton ``AsyncPostgresSaver`` bound to the application's async
PostgreSQL pool.  Used by the compiled agent graph to persist checkpoint
state across process restarts (enables resume + HITL + time-travel).
"""

from __future__ import annotations

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.memory.checkpointer")

_checkpointer: AsyncPostgresSaver | None = None
_pool: AsyncConnectionPool | None = None


def create_pool() -> AsyncConnectionPool:
    """Create an ``AsyncConnectionPool`` from the application's database URL.

    The pool uses the same connection string as the SQLAlchemy engine but
    replaces the ``+asyncpg`` driver suffix with the raw PostgreSQL scheme
    that psycopg expects.
    """
    settings = get_settings()
    raw_url = settings.database.url
    pg_url = raw_url.replace("postgresql+asyncpg://", "postgresql://")
    return AsyncConnectionPool(pg_url, min_size=1, max_size=5)


async def get_checkpointer() -> AsyncPostgresSaver:
    """Return a singleton ``AsyncPostgresSaver`` connected via an async pool.

    The first call creates the pool, connects the saver with ``autocommit``
    and ``dict_row`` (both required by LangGraph's PostgresSaver), runs
    ``setup()`` to ensure checkpoint tables exist, and caches the instance.
    """
    global _checkpointer, _pool  # noqa: PLW0603

    if _checkpointer is not None:
        return _checkpointer

    if _pool is None:
        _pool = create_pool()
    conn = await _pool.connection()
    conn.autocommit = True
    conn.row_factory = dict_row
    saver = AsyncPostgresSaver(conn=conn)
    await saver.setup()
    _checkpointer = saver
    logger.info("checkpointer.initialized")
    return _checkpointer


def get_sync_checkpointer() -> AsyncPostgresSaver | None:
    """Return the cached checkpointer if already initialised."""
    return _checkpointer


async def close_checkpointer() -> None:
    """Close the underlying connection pool."""
    global _checkpointer, _pool  # noqa: PLW0603

    _checkpointer = None
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("checkpointer.closed")
