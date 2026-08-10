"""Worker — executes queued tasks in the background.

The orchestrator stays stateless: heavy/long-running work (reports, ETL,
browser automation, scheduled workflow runs) is enqueued by the API layer
and executed here. Lifecycle: claim → mark running → execute (with progress
and cancellation checks) → ack/complete or nack/fail.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
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
    """Background task worker: claims tasks from the queue and executes them.

    D5/P0-D lease semantics: each worker uses a UNIQUE consumer name (so
    horizontal parallelism works), holds an atomic DB lease on the task
    row while executing (heartbeated), releases it on completion, and can
    only ever commit writes while it still owns the lease.
    """

    def __init__(
        self,
        registry: TaskRegistry | None = None,
        queue: TaskQueue | None = None,
        poll_ms: int = 500,
        consumer: str | None = None,
        lease_s: int = 60,
    ) -> None:
        self._registry = registry or TaskRegistry()
        self._queue = queue or RedisStreamsQueue()
        self._poll_ms = poll_ms
        # D5: unique consumer name per worker process — all workers sharing
        # the name "worker" would be ONE consumer from Redis's perspective.
        self._consumer = consumer or f"worker-{uuid.uuid4().hex[:8]}"
        self._lease_s = lease_s
        self._running = False

    async def run_once(self) -> bool:
        """Claim and execute ONE task. Returns True if a task was processed."""
        claimed = await self._queue.claim(consumer=self._consumer)
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

        # D5: ATOMIC DB LEASE — exactly one worker may execute. When the
        # lease is held by another worker (stream XCLAIM raced), the task
        # must NOT run; the entry stays pending and is retried after the
        # lease expires.
        if not await self._registry.claim_lease(task_id, self._consumer, self._lease_s):
            logger.info(
                "worker.lease_held_by_another",
                task_id=task_id,
                holder=record.get("worker_id"),
            )
            return True

        await self._registry.update_status(task_id, STATUS_RUNNING)
        executor = _executors.get(record.get("task_type", ""))
        if executor is None:
            await self._registry.mark_failed(task_id, f"No executor for task type '{record.get('task_type')}'")
            await self._registry.release_lease(task_id, self._consumer)
            await self._queue.ack(entry_id)
            return True

        # D5: lease heartbeat while executing — a crash mid-run expires
        # the lease for a safe reclaim; a lost lease means the worker must
        # stop committing.
        heartbeat_task: asyncio.Task[None] | None = None

        async def _heartbeat() -> None:
            while True:
                await asyncio.sleep(max(1, self._lease_s // 3))
                await self._registry.heartbeat(task_id, self._consumer, self._lease_s)

        try:
            heartbeat_task = asyncio.create_task(_heartbeat())
            result = await executor(payload)
            await self._registry.mark_completed(task_id, result if isinstance(result, dict) else {"result": result})
            await self._queue.ack(entry_id)
            logger.info("worker.task_completed", task_id=task_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("worker.task_failed", task_id=task_id, error=str(exc)[:300])
            # D5: retry semantics — a failed task is left pending (not
            # acked) while attempts remain; max_attempts exhausted →
            # terminal FAILED.
            if await self._registry.register_attempt(task_id):
                logger.info("worker.task_retry_pending", task_id=task_id)
            else:
                await self._registry.mark_failed(task_id, str(exc)[:500])
                await self._queue.ack(entry_id)
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            await self._registry.release_lease(task_id, self._consumer)
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
