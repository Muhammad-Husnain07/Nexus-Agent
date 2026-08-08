"""Worker — executes queued tasks in the background.

The orchestrator stays stateless: heavy/long-running work (reports, ETL,
browser automation, scheduled workflow runs) is enqueued by the API layer
and executed here. Lifecycle: claim → mark running → execute (with progress
and cancellation checks) → ack/complete or nack/fail.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import structlog

from nexus.providers.queue.base import TaskQueue
from nexus.providers.queue.redis_streams import RedisStreamsQueue
from nexus.tasks.registry import (
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    TaskRegistry,
)

logger = structlog.get_logger("nexus.tasks.worker")

# Task-type → executor registry (dynamic: any registered callable).
# Executors are registered via ``register_executor("type", fn)`` — no
# hardcoded dispatch chains.
_executors: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {}


def register_executor(task_type: str, fn: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
    """Register an async executor for a task type."""
    _executors[task_type] = fn


def get_executors() -> dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]:
    """Return the registered task executors (for inspection/tests)."""
    return dict(_executors)


class Worker:
    """Background task worker: claims tasks from the queue and executes them."""

    def __init__(
        self,
        registry: TaskRegistry | None = None,
        queue: TaskQueue | None = None,
        poll_ms: int = 500,
    ) -> None:
        self._registry = registry or TaskRegistry()
        self._queue = queue or RedisStreamsQueue()
        self._poll_ms = poll_ms
        self._running = False

    async def run_once(self) -> bool:
        """Claim and execute ONE task. Returns True if a task was processed."""
        claimed = await self._queue.claim()
        if claimed is None:
            return False
        task_id = claimed["task_id"]
        entry_id = claimed.get("entry_id", "")
        payload = dict(claimed.get("payload", {}) or {})
        # Inject the task identity so executors can write progress/results
        # back (typed ExecutionRequest lifecycle).
        payload["_task_id"] = task_id

        # Guard: a task that was cancelled before pickup should not run
        record = await self._registry.get(task_id)
        if record is None:
            await self._queue.ack(entry_id)
            return True
        if record.get("cancel_requested"):
            await self._registry.update_status(task_id, STATUS_CANCELLED)
            await self._queue.ack(entry_id)
            return True

        await self._registry.update_status(task_id, STATUS_RUNNING)
        executor = _executors.get(record.get("task_type", ""))
        if executor is None:
            await self._registry.mark_failed(task_id, f"No executor for task type '{record.get('task_type')}'")
            await self._queue.ack(entry_id)
            return True

        try:
            result = await executor(payload)
            await self._registry.mark_completed(task_id, result if isinstance(result, dict) else {"result": result})
            await self._queue.ack(entry_id)
            logger.info("worker.task_completed", task_id=task_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("worker.task_failed", task_id=task_id, error=str(exc)[:300])
            await self._registry.mark_failed(task_id, str(exc)[:500])
            await self._queue.ack(entry_id)
        return True

    async def run_forever(self) -> None:
        """Poll and execute tasks until cancelled."""
        self._running = True
        logger.info("worker.started")
        while self._running:
            try:
                await self.run_once()
            except Exception as exc:
                logger.error("worker.iteration_failed", error=str(exc)[:300])
            await asyncio.sleep(self._poll_ms / 1000)

    def stop(self) -> None:
        self._running = False


async def run_worker_loop(poll_ms: int | None = None) -> None:
    """Entry point for the ``nexus worker`` CLI.

    Initializes GlobalContext first — the worker executes the FULL agent
    graph, which needs the same O(1) capability indexes the API process
    builds at startup (compiled graph + tool table).
    """
    from nexus.config.settings import get_settings

    try:
        from nexus.compiler.compiled_graph import load_compiled_graph_async
        from nexus.context.global_context import GlobalContext, set_global_context
        from nexus.db.base import async_session as _worker_db

        compiled = await load_compiled_graph_async()
        if compiled:
            async with _worker_db() as _db:
                ctx = await GlobalContext.build(compiled, tool_session=_db)
            set_global_context(ctx)
            logger.info("worker.global_context_ready", capabilities=len(ctx.capability_index))
    except Exception as exc:
        logger.warning("worker.global_context_init_failed", error=str(exc)[:200])

    settings = get_settings()
    worker = Worker(poll_ms=poll_ms or settings.queue.worker_poll_ms)
    try:
        await worker.run_forever()
    except asyncio.CancelledError:
        worker.stop()
        logger.info("worker.stopped")
