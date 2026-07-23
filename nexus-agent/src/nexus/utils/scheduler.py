"""Background task scheduler for periodic maintenance jobs.

Runs memory consolidation, decay, and other housekeeping tasks on
configurable intervals using asyncio background tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.scheduler")

_CONSOLIDATION_INTERVAL_S: int = 1800  # 30 min
_DECAY_INTERVAL_S: int = 3600  # 60 min


async def _memory_maintenance_loop() -> None:
    """Background maintenance loop: consolidation + decay.

    Runs consolidation every 30 min (configurable via settings) and decay
    every other cycle. Consolidation only proceeds if there are enough
    active memories (> 10) to justify the cost.
    """
    cycle = 0
    while True:
        consolidation_interval = get_settings().memory.consolidation_interval_minutes * 60
        await asyncio.sleep(consolidation_interval)
        cycle += 1

        try:
            from nexus.memory.consolidator import MemoryConsolidator  # noqa: PLC0415

            consolidator = MemoryConsolidator()
            report = await consolidator.consolidate_all()
            logger.info(
                "scheduler.consolidation.completed",
                merged=report.clusters_merged,
                promoted=report.memories_promoted,
                deduped=report.duplicates_removed,
                archived=report.memories_archived,
            )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("scheduler.consolidation.failed", error=str(exc))

        # Run decay every other cycle
        if cycle % 2 == 0:
            try:
                from nexus.memory.manager import MemoryManager  # noqa: PLC0415

                manager = MemoryManager()
                archived = await manager.decay()
                logger.info("scheduler.decay.completed", archived=archived)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("scheduler.decay.failed", error=str(exc))


_task: asyncio.Task[Any] | None = None


async def start_scheduler() -> None:
    """Start the background scheduler task."""
    global _task  # noqa: PLW0603
    if _task is not None:
        return
    _task = asyncio.create_task(_memory_maintenance_loop())
    logger.info("scheduler.started")


async def stop_scheduler() -> None:
    """Cancel and await the background scheduler task."""
    global _task  # noqa: PLW0603
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
        logger.info("scheduler.stopped")
