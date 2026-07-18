"""Background task scheduler for periodic maintenance jobs.

Runs memory decay and other housekeeping tasks on a configurable interval.
Uses asyncio background tasks started during the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog

logger = structlog.get_logger("nexus.scheduler")

_DECAY_INTERVAL_S: int = 3600


async def _memory_decay_loop(interval_s: int = _DECAY_INTERVAL_S) -> None:
    """Periodically run memory decay to reduce importance of stale memories."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            from nexus.memory.manager import MemoryManager

            manager = MemoryManager()
            await manager.decay()
            logger.info("scheduler.memory_decay.completed")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("scheduler.memory_decay.failed", error=str(exc))


_task: asyncio.Task[Any] | None = None


async def start_scheduler(interval_s: int = _DECAY_INTERVAL_S) -> None:
    """Start the background scheduler task."""
    global _task  # noqa: PLW0603
    if _task is not None:
        return
    _task = asyncio.create_task(_memory_decay_loop(interval_s))
    logger.info("scheduler.started", interval_s=interval_s)


async def stop_scheduler() -> None:
    """Cancel and await the background scheduler task."""
    global _task  # noqa: PLW0603
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
        logger.info("scheduler.stopped")
