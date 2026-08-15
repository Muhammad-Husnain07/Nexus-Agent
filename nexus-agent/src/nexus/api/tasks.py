"""Tasks API — create, inspect, pause/resume/cancel persistent background tasks.

The orchestrator hands heavy work to the task queue (Redis Streams) and the
``nexus-worker`` process; this router is the control plane: enqueue new
tasks, watch progress, and manage lifecycle.

PH-3 tenant scoping: a task created under a session is addressable only by
the session's owner (same boundary as chat/memory). Session-less tasks
(operator/system) remain open.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from nexus.providers.queue.base import TaskQueue
from nexus.providers.queue.redis_streams import RedisStreamsQueue
from nexus.security.ownership import accessible_session_ids
from nexus.tasks.registry import TaskRegistry

logger = structlog.get_logger("nexus.api.tasks")

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    """Request to create + enqueue a background task."""

    task_type: str = Field(description="Registered task type (e.g. workflow_run, report, etl)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Task input payload")
    session_id: str | None = Field(default=None, description="Originating session id")
    max_attempts: int = Field(default=3, ge=1, le=10, description="Max attempts before failure")
    schedule_cron: str | None = Field(default=None, description="Cron expression for recurring runs")
    next_run_at: str | None = Field(default=None, description="ISO timestamp for one-shot scheduling")


async def _registry() -> TaskRegistry:
    return TaskRegistry()


async def _queue() -> TaskQueue:
    return RedisStreamsQueue()


async def _task_accessible(request: Request, task: dict[str, Any] | None) -> bool:
    """PH-3: a session-bound task is visible only to the session's owner.

    Session-less tasks (system/operator, legacy rows) stay open — the same
    posture the session layer uses for legacy NULL-owner rows.
    """
    if not task:
        return False
    session_id = task.get("session_id")
    if not session_id:
        return True
    try:
        accessible = await accessible_session_ids(request)
        return uuid.UUID(str(session_id)) in accessible
    except Exception:
        return False


@router.post("", status_code=201)
async def create_task(body: TaskCreate, request: Request) -> dict[str, Any]:
    """Create a task record and enqueue it (or schedule it)."""
    from datetime import UTC, datetime

    if body.session_id:
        if not await _task_accessible(request, {"session_id": body.session_id}):
            raise HTTPException(status_code=403, detail="Session not accessible")

    next_run = None
    if body.next_run_at:
        try:
            next_run = datetime.fromisoformat(body.next_run_at.replace("Z", "+00:00"))
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=UTC)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid next_run_at: {exc}") from exc

    registry = await _registry()
    task = await registry.create(
        task_type=body.task_type,
        payload=body.payload,
        session_id=body.session_id,
        max_attempts=body.max_attempts,
        schedule_cron=body.schedule_cron,
        next_run_at=next_run,
    )

    # Immediate tasks go straight to the queue; scheduled ones wait for the
    # scheduler to enqueue them at next_run_at.
    if not body.schedule_cron and next_run is None:
        q = await _queue()
        try:
            await q.enqueue(task["id"], body.payload)
        except Exception as exc:
            await registry.update_status(task["id"], "failed", error_message=str(exc)[:300])
            raise HTTPException(status_code=503, detail=f"Queue unavailable: {exc}") from exc
        task = await registry.update_status(task["id"], "queued") or task

    logger.info("tasks.created", task_id=task["id"], task_type=body.task_type)
    # Durable domain event for event-driven consumers (outbox relay).
    from nexus.events.service import enqueue_outbox

    try:
        await enqueue_outbox(
            event_type="task.created",
            aggregate_type="task",
            aggregate_id=task["id"],
            payload={"task_type": body.task_type, "status": task.get("status", "pending")},
        )
    except Exception as exc:
        logger.warning("tasks.outbox_failed", error=str(exc)[:200])
    return task


@router.get("")
async def list_tasks(
    request: Request,
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List tasks with optional filters (PH-3: session-scoped)."""
    registry = await _registry()
    tasks = await registry.list(status=status, task_type=task_type, limit=min(limit, 200))
    visible = [t for t in tasks if await _task_accessible(request, t)]
    return {"tasks": visible, "count": len(visible)}


async def _owned_task(request: Request, task_id: str) -> dict[str, Any]:
    """Fetch a task and enforce tenant access (PH-3)."""
    registry = await _registry()
    task = await registry.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not await _task_accessible(request, task):
        raise HTTPException(status_code=403, detail="Task not accessible")
    return task


@router.get("/{task_id}")
async def get_task(task_id: str, request: Request) -> dict[str, Any]:
    """Get a single task by id."""
    return await _owned_task(request, task_id)


@router.post("/{task_id}/pause")
async def pause_task(task_id: str, request: Request) -> dict[str, Any]:
    """Pause a task (worker stops advancing it)."""
    await _owned_task(request, task_id)
    registry = await _registry()
    task = await registry.pause(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/resume")
async def resume_task(task_id: str, request: Request) -> dict[str, Any]:
    """Resume a paused task (re-enqueues for worker pickup)."""
    await _owned_task(request, task_id)
    registry = await _registry()
    task = await registry.resume(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    q = await _queue()
    await q.enqueue(task["id"], task.get("payload", {}))
    return task


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> dict[str, Any]:
    """Request cancellation — the worker checks the flag between steps."""
    await _owned_task(request, task_id)
    registry = await _registry()
    task = await registry.request_cancel(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
