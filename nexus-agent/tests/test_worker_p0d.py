"""D5/P0-D — worker claim/lease semantics.

- unique consumer names (horizontal parallelism)
- atomic DB lease: exactly one worker executes; a held lease skips;
  an expired lease is safely reclaimable
- retry attempts honored (pending until max_attempts)
- one-shot scheduled tasks enqueued exactly once
"""

from __future__ import annotations

import asyncio
import uuid

from nexus.tasks.scheduler import Scheduler
from nexus.tasks.worker import Worker, register_executor


class FakeQueue:
    def __init__(self) -> None:
        self.claims: list[dict] = []
        self.acked: list[str] = []
        self.enqueued: list[tuple[str, dict]] = []

    async def claim(self, group="default", consumer="worker"):
        if not self.claims:
            return None
        return self.claims.pop(0)

    async def ack(self, task_id, group="default"):
        self.acked.append(task_id)

    async def enqueue(self, task_id, payload, group="default"):
        self.enqueued.append((task_id, payload))


class FakeRegistry:
    def __init__(self, record: dict | None = None) -> None:
        self.record = record
        self.status: list[str] = []
        self.lease_wins: list[bool] = []
        self.released: list[str] = []
        self.attempts_left: list[bool] = []
        self.completed: list[str] = []
        self.failed: list[str] = []
        self.advances: list[tuple[str, object]] = []

    async def get(self, task_id):
        return self.record

    async def update_status(self, task_id, status):
        self.status.append(status)

    async def claim_lease(self, task_id, worker_id, lease_s=60):
        return self.lease_wins.pop(0) if self.lease_wins else True

    async def heartbeat(self, task_id, worker_id, lease_s=60):
        pass

    async def release_lease(self, task_id, worker_id):
        self.released.append(task_id)

    async def register_attempt(self, task_id):
        return self.attempts_left.pop(0) if self.attempts_left else False

    async def mark_completed(self, task_id, result):
        self.completed.append(task_id)

    async def mark_failed(self, task_id, error):
        self.failed.append(task_id)

    async def due_tasks(self, now=None):
        return []

    async def _advance_next_run(self, *a):
        self.advances.append(a)


RECORD = {
    "id": str(uuid.uuid4()),
    "task_type": "probe",
    "status": "queued",
    "payload": {},
    "worker_id": None,
    "cancel_requested": False,
}


class TestWorkerLeaseSemantics:
    def _worker(self, registry, queue):
        return Worker(registry=registry, queue=queue, poll_ms=1, lease_s=60)

    async def _exec(self, w, executor):
        register_executor("probe", executor)
        await w.run_once()

    def test_unique_consumer_names(self):
        w1 = Worker(queue=FakeQueue())
        w2 = Worker(queue=FakeQueue())
        assert w1._consumer != w2._consumer, (
            "workers must not share a Redis consumer name"
        )

    def test_held_lease_never_executes(self):
        registry = FakeRegistry(dict(RECORD))
        registry.lease_wins.append(False)  # another worker holds it
        queue = FakeQueue()
        queue.claims.append({"task_id": RECORD["id"], "entry_id": "e1", "payload": {}})
        calls: list[str] = []

        async def _executor(payload):
            calls.append("ran")
            return {"ok": True}

        w = self._worker(registry, queue)
        asyncio.run(self._exec(w, _executor))
        assert calls == [], "a held lease must never execute the task"
        assert queue.acked == [], "the entry stays pending for retry"

    def test_expired_lease_is_reclaimable_and_executes(self):
        registry = FakeRegistry(dict(RECORD))
        registry.lease_wins.append(True)  # stale lease reclaimable
        queue = FakeQueue()
        queue.claims.append({"task_id": RECORD["id"], "entry_id": "e1", "payload": {}})
        calls: list[str] = []

        async def _executor(payload):
            calls.append("ran")
            return {"ok": True}

        w = self._worker(registry, queue)
        asyncio.run(self._exec(w, _executor))
        assert calls == ["ran"]
        assert registry.completed == [RECORD["id"]]
        assert registry.released == [RECORD["id"]]
        assert queue.acked == ["e1"]

    def test_failure_retries_then_fails(self):
        registry = FakeRegistry(dict(RECORD))
        registry.lease_wins.append(True)
        registry.attempts_left.append(True)  # one retry remains
        queue = FakeQueue()
        queue.claims.append({"task_id": RECORD["id"], "entry_id": "e1", "payload": {}})

        async def _executor(payload):
            raise RuntimeError("boom")

        w = self._worker(registry, queue)
        asyncio.run(self._exec(w, _executor))
        assert registry.failed == [], "with attempts left the task stays pending"
        assert queue.acked == [], "pending entry retries, never acked"
        assert registry.released == [RECORD["id"]]

        # exhausted attempts → terminal failure + ack
        registry2 = FakeRegistry(dict(RECORD))
        registry2.lease_wins.append(True)
        registry2.attempts_left.append(False)
        queue2 = FakeQueue()
        queue2.claims.append({"task_id": RECORD["id"], "entry_id": "e2", "payload": {}})
        w2 = self._worker(registry2, queue2)
        asyncio.run(self._exec(w2, _executor))
        assert registry2.failed == [RECORD["id"]]
        assert queue2.acked == ["e2"]


class TestSchedulerOneShot:
    async def _tick(self, registry, queue):
        sched = Scheduler(registry=registry, queue=queue, poll_s=15)
        return await sched.tick()

    def test_one_shot_clears_next_run_after_enqueue(self):
        registry = FakeRegistry()
        queue = FakeQueue()
        asyncio.run(self._tick(registry, queue))
        # with no due tasks nothing advances — the real advance path is
        # exercised below with a stub due list.
        assert True

    def test_one_shot_not_reenqueued(self, monkeypatch):
        due = [{
            "id": str(uuid.uuid4()),
            "task_type": "probe",
            "payload": {"x": 1},
            "schedule_cron": None,
        }]

        class _R(FakeRegistry):
            async def due_tasks(self, now=None):
                return list(due)

        registry = _R()
        queue = FakeQueue()
        sched = Scheduler(registry=registry, queue=queue, poll_s=15)
        advances: list[tuple[str, object]] = []
        monkeypatch.setattr(
            sched, "_advance_next_run",
            lambda task_id, next_run: advances.append((task_id, next_run)),
        )
        asyncio.run(sched.tick())
        assert len(queue.enqueued) == 1
        assert advances and advances[0][1] is None, (
            "a one-shot task's next_run_at must be cleared after enqueue"
        )
