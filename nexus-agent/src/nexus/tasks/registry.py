"""TaskRegistry — persistent CRUD over the ``task`` table.

The orchestrator stays stateless: heavy or long-running work is handed to
background workers via the task queue (Redis Streams); this registry is the
durable record for status, progress, retries, cancellation, and scheduling.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

import structlog

from nexus.db.base import async_session as _async_session
from nexus.db.models.task import Task

logger = structlog.get_logger("nexus.tasks.registry")


# Task lifecycle statuses
STATUS_PENDING = "pending"
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


class TaskNotFoundError(Exception):
    """Raised when a task id does not exist."""


class TaskRegistry:
    """CRUD + state transitions for persistent tasks."""

    async def create(
        self,
        task_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
        max_attempts: int = 3,
        schedule_cron: str | None = None,
        next_run_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Create a task record (status=pending)."""
        task = Task(
            id=uuid.uuid4(),
            session_id=uuid.UUID(session_id) if session_id else None,
            task_type=task_type,
            payload=payload,
            status=STATUS_PENDING,
            max_attempts=max_attempts,
            schedule_cron=schedule_cron,
            next_run_at=next_run_at,
        )
        async with _async_session() as sess:
            sess.add(task)
            await sess.commit()
        logger.info("task.created", task_id=str(task.id), task_type=task_type)
        return self._row(task)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        """Fetch a task by id."""
        try:
            tid = uuid.UUID(task_id)
        except (ValueError, TypeError):
            return None
        async with _async_session() as sess:
            result = await sess.execute(select(Task).where(Task.id == tid))
            task = result.scalar_one_or_none()
            return self._row(task) if task else None

    async def list(
        self,
        status: str | None = None,
        task_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List tasks, optionally filtered."""
        stmt = select(Task).order_by(Task.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(Task.status == status)
        if task_type:
            stmt = stmt.where(Task.task_type == task_type)
        async with _async_session() as sess:
            result = await sess.execute(stmt)
            return [self._row(t) for t in result.scalars().all()]

    async def update_status(
        self,
        task_id: str,
        status: str,
        error_message: str | None = None,
        result: dict[str, Any] | None = None,
        progress: int | None = None,
    ) -> dict[str, Any] | None:
        """Transition a task's status."""
        values: dict[str, Any] = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if result is not None:
            values["result"] = result
        if progress is not None:
            values["progress"] = max(0, min(100, int(progress)))
        now = datetime.now(UTC)
        if status == STATUS_RUNNING:
            values["started_at"] = now
        elif status in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED):
            values["completed_at"] = now
        values["updated_at"] = now

        try:
            tid = uuid.UUID(task_id)
        except (ValueError, TypeError):
            return None
        async with _async_session() as sess:
            result_row = await sess.execute(
                update(Task).where(Task.id == tid).values(**values).returning(Task)
            )
            task = result_row.scalar_one_or_none()
            if task is None:
                return None
            await sess.commit()
        logger.info("task.updated", task_id=task_id, status=status)
        return self._row(task)

    async def update_progress(self, task_id: str, progress: int) -> dict[str, Any] | None:
        """Update a task's progress percentage (0-100) without a status change."""
        try:
            tid = uuid.UUID(task_id)
        except (ValueError, TypeError):
            return None
        async with _async_session() as sess:
            task = (await sess.execute(select(Task).where(Task.id == tid))).scalar_one_or_none()
            if task is None:
                return None
            task.progress = max(0, min(100, int(progress)))
            await sess.commit()
            # expire_on_commit detaches attributes — reload before serializing.
            await sess.refresh(task)
        return self._row(task)

    async def mark_attempt(self, task_id: str) -> dict[str, Any] | None:
        """Increment the attempt counter when a worker starts processing."""
        task = await self.get(task_id)
        if task is None:
            return None
        return await self.update_status(
            task_id,
            STATUS_RUNNING,
            progress=task.get("progress", 0),
        )

    async def request_cancel(self, task_id: str) -> dict[str, Any] | None:
        """Set the cancellation flag — the worker checks it between steps."""
        try:
            tid = uuid.UUID(task_id)
        except (ValueError, TypeError):
            return None
        async with _async_session() as sess:
            result = await sess.execute(
                update(Task)
                .where(Task.id == tid)
                .values(cancel_requested=True)
                .returning(Task)
            )
            task = result.scalar_one_or_none()
            if task is None:
                return None
            await sess.commit()
        logger.info("task.cancel_requested", task_id=task_id)
        return self._row(task)

    async def pause(self, task_id: str) -> dict[str, Any] | None:
        """Pause a running/queued task."""
        return await self.update_status(task_id, STATUS_PAUSED)

    async def resume(self, task_id: str) -> dict[str, Any] | None:
        """Resume a paused task (back to queued for worker pickup)."""
        return await self.update_status(task_id, STATUS_QUEUED)

    async def mark_completed(self, task_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
        return await self.update_status(task_id, STATUS_COMPLETED, result=result, progress=100)

    async def mark_failed(self, task_id: str, error: str) -> dict[str, Any] | None:
        return await self.update_status(task_id, STATUS_FAILED, error_message=error)

    async def due_tasks(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Scheduled tasks whose next_run_at has passed (scheduler poll)."""
        now = now or datetime.now(UTC)
        stmt = (
            select(Task)
            .where(
                Task.status.in_([STATUS_PENDING, STATUS_QUEUED]),
                Task.next_run_at.is_not(None),
                Task.next_run_at <= now,
            )
            .order_by(Task.next_run_at.asc())
            .limit(50)
        )
        async with _async_session() as sess:
            result = await sess.execute(stmt)
            return [self._row(t) for t in result.scalars().all()]

    @staticmethod
    def _row(task: Task) -> dict[str, Any]:
        return {
            "id": str(task.id),
            "session_id": str(task.session_id) if task.session_id else None,
            "task_type": task.task_type,
            "status": task.status,
            "payload": task.payload,
            "result": task.result,
            "progress": task.progress,
            "attempts": task.attempts,
            "max_attempts": task.max_attempts,
            "cancel_requested": task.cancel_requested,
            "schedule_cron": task.schedule_cron,
            "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
            "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
            "error_message": task.error_message,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }
