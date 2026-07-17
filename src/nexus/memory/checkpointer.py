"""Persistent LangGraph checkpointer via AsyncPostgresSaver.

Provides a singleton ``AsyncPostgresSaver`` bound to the application's async
PostgreSQL pool.  Used by the compiled agent graph to persist checkpoint
state across process restarts (enables resume + HITL + time-travel).

On Windows (where psycopg async doesn't work with ProactorEventLoop), this
module gracefully returns ``None``, allowing the graph to fall back to
``MemorySaver``.
"""

from __future__ import annotations

import sys

import structlog

logger = structlog.get_logger("nexus.memory.checkpointer")

_checkpointer = None
_pool = None


async def get_checkpointer():
    """Return a singleton ``AsyncPostgresSaver`` or ``None``.

    Returns ``None`` on platforms where psycopg async is unavailable
    (Windows + ProactorEventLoop), allowing fallback to ``MemorySaver``.
    """
    global _checkpointer, _pool  # noqa: PLW0603

    if _checkpointer is not None:
        return _checkpointer

    if sys.platform == "win32":
        logger.warning("checkpointer.unavailable_on_windows")
        return None

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        from nexus.config.settings import get_settings

        settings = get_settings()
        raw_url = settings.database.url
        pg_url = raw_url.replace("postgresql+asyncpg://", "postgresql://")
        _pool = AsyncConnectionPool(pg_url, min_size=1, max_size=5)
        conn_cm = _pool.connection()
        conn = await conn_cm.__aenter__()
        conn.autocommit = True
        conn.row_factory = dict_row
        saver = AsyncPostgresSaver(conn=conn)
        await saver.setup()
        _checkpointer = saver
        logger.info("checkpointer.initialized")
    except Exception as exc:
        logger.warning("checkpointer.init_failed", error=str(exc))
        if _pool is not None:
            await _pool.close()
            _pool = None
        return None
    return _checkpointer


def get_sync_checkpointer():
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
