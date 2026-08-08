"""Scheduler — polls for due tasks and enqueues them.

Handles two scheduling sources:
- ``next_run_at`` timestamps (one-shot or re-occurring)
- ``schedule_cron`` expressions (croniter) for recurring tasks

After enqueueing a recurring task it advances ``next_run_at`` so the task
can run again. Cron parsing is delegated to ``croniter`` (pluggable).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog

from nexus.providers.queue.base import TaskQueue
from nexus.providers.queue.redis_streams import RedisStreamsQueue
from nexus.tasks.registry import STATUS_QUEUED, TaskRegistry

logger = structlog.get_logger("nexus.tasks.scheduler")


class Scheduler:
    """Polls the task registry for due scheduled tasks."""

    def __init__(
        self,
        registry: TaskRegistry | None = None,
        queue: TaskQueue | None = None,
        poll_s: int = 15,
    ) -> None:
        self._registry = registry or TaskRegistry()
        self._queue = queue or RedisStreamsQueue()
        self._poll_s = poll_s
        self._running = False

    async def tick(self) -> int:
        """Enqueue all due tasks. Returns the number enqueued."""
        due = await self._registry.due_tasks()
        enqueued = 0
        for task in due:
            task_id = task["id"]
            # Recurring tasks: advance next_run_at BEFORE enqueue so a crash
            # mid-run doesn't double-schedule (at-least-once tradeoff).
            if task.get("schedule_cron"):
                await self._registry.update_status(task_id, STATUS_QUEUED)
                nxt = _next_cron(task["schedule_cron"])
                await self._advance_next_run(task_id, nxt)
            else:
                await self._registry.update_status(task_id, STATUS_QUEUED)
            try:
                await self._queue.enqueue(task_id, task.get("payload", {}))
                enqueued += 1
                logger.info("scheduler.enqueued", task_id=task_id, task_type=task.get("task_type"))
            except Exception as exc:
                logger.warning("scheduler.enqueue_failed", task_id=task_id, error=str(exc)[:200])
        return enqueued

    async def _advance_next_run(self, task_id: str, next_run: datetime | None) -> None:
        """Persist the next scheduled run (or clear if one-shot)."""
        from sqlalchemy import update as _update

        from nexus.db.base import async_session as _sess
        from nexus.db.models.task import Task

        values = {"next_run_at": next_run}
        async with _sess() as sess:
            await sess.execute(_update(Task).where(Task.id == _as_uuid(task_id)).values(**values))
            await sess.commit()

    async def run_forever(self) -> None:
        self._running = True
        logger.info("scheduler.started", poll_s=self._poll_s)
        while self._running:
            try:
                await self.tick()
            except Exception as exc:
                logger.error("scheduler.tick_failed", error=str(exc)[:300])
            await asyncio.sleep(self._poll_s)

    def stop(self) -> None:
        self._running = False


def _as_uuid(task_id: str):
    import uuid

    return uuid.UUID(task_id)


def _next_cron(expr: str) -> datetime | None:
    """Compute the next run time from a cron expression."""
    try:
        from croniter import croniter

        base = datetime.now(UTC)
        return croniter(expr, base).get_next(datetime)
    except Exception:
        try:
            return datetime.now(UTC) + timedelta(minutes=5)
        except Exception:
            return None
