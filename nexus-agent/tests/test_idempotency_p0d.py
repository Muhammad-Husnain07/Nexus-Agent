"""D1/P0-D — durable idempotency ledger (I5).

Identity = (session, operation, resolved inputs); attempt ids never
participate. Exactly one winner executes; others observe the completed
result; reflection-style fresh executor instances replay instead of
re-executing.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from nexus.execution.ledger import CompletedExecutionLedger, LedgerEntry


class FakeLedgerStore:
    """Dict-backed store mirroring the SQL lease semantics."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.fail_operations: set[str] = set()

    def _fail(self, op: str) -> bool:
        return op in self.fail_operations

    async def find(self, session_id, execution_key):
        row = self.rows.get((session_id, execution_key))
        if row is None:
            return None
        return LedgerEntry(
            result=row["result"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            arch_fp=row["arch_fp"],
        )

    async def claim(self, session_id, execution_key, token, lease_s, arch_fp, agent_run_id=None):
        if self._fail("claim"):
            raise RuntimeError("db down")
        key = (session_id, execution_key)
        now = datetime.now(UTC)
        if key not in self.rows:
            self.rows[key] = {
                "result": None, "lease_token": token,
                "lease_expires_at": now + timedelta(seconds=lease_s),
                "arch_fp": arch_fp,
            }
            return True
        row = self.rows[key]
        if row["result"] is not None:
            return False
        lease = row["lease_expires_at"]
        if lease is None or lease < now:
            row["lease_token"] = token
            row["lease_expires_at"] = now + timedelta(seconds=lease_s)
            row["arch_fp"] = arch_fp
            return True
        return False

    async def complete(self, session_id, execution_key, result, token, agent_run_id=None):
        if self._fail("complete"):
            raise RuntimeError("db down")
        row = self.rows.get((session_id, execution_key))
        if row and row["lease_token"] == token:
            row["result"] = result
            row["lease_token"] = None
            row["lease_expires_at"] = None

    async def release(self, session_id, execution_key, token):
        if self._fail("release"):
            raise RuntimeError("db down")
        row = self.rows.get((session_id, execution_key))
        if row and row["lease_token"] == token:
            row["lease_token"] = None
            row["lease_expires_at"] = None


class TestLedgerSemantics:
    def test_claim_then_reuse(self):
        store = FakeLedgerStore()
        ledger = CompletedExecutionLedger(store=store)

        async def _run():
            tok = await ledger.claim("s1", "k1", "fp")
            assert tok is not None
            await ledger.complete("s1", "k1", {"ok": 1}, tok)
            entry = await ledger.find("s1", "k1")
            return entry

        entry = asyncio.run(_run())
        assert entry.result == {"ok": 1}
        assert entry.lease_token is None

    def test_exactly_one_winner(self):
        store = FakeLedgerStore()
        ledger = CompletedExecutionLedger(store=store)

        async def _run():
            a = await ledger.claim("s1", "k1", "fp")
            b = await ledger.claim("s1", "k1", "fp")
            return a, b

        a, b = asyncio.run(_run())
        assert a is not None
        assert b is None, "only one attempt may win the claim"

    def test_stale_lease_reclaimable(self):
        store = FakeLedgerStore()
        ledger = CompletedExecutionLedger(store=store, lease_s=120)

        async def _run():
            tok = await ledger.claim("s1", "k1", "fp")
            # expire the lease (simulated crash of the holder)
            row = store.rows[("s1", "k1")]
            row["lease_expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
            tok2 = await ledger.claim("s1", "k1", "fp")
            return tok, tok2

        tok, tok2 = asyncio.run(_run())
        assert tok is not None
        assert tok2 is not None, "an expired lease must be reclaimable"

    def test_completed_result_never_reclaimed(self):
        store = FakeLedgerStore()
        ledger = CompletedExecutionLedger(store=store)

        async def _run():
            tok = await ledger.claim("s1", "k1", "fp")
            await ledger.complete("s1", "k1", {"done": True}, tok)
            tok2 = await ledger.claim("s1", "k1", "fp")
            return tok2

        assert asyncio.run(_run()) is None

    def test_degrade_on_store_failure(self):
        store = FakeLedgerStore()
        store.fail_operations.add("claim")
        ledger = CompletedExecutionLedger(store=store)
        tok = asyncio.run(ledger.claim("s1", "k1", "fp"))
        assert tok is not None, "a store failure must degrade to execution, never block"


class _FakeToolExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, tool, inputs, context, session, skip_approval=False):
        self.calls.append((tool.name, dict(inputs)))
        from nexus.tools.result import ToolResult

        return ToolResult(
            tool_id=uuid.uuid4(),
            tool_name=tool.name,
            status="success",
            data={"echo": inputs},
            duration_ms=1,
            http_status=200,
        )


class _Task:
    def __init__(self, tid: str, tool: str, inputs: dict) -> None:
        self.id = tid
        self.tool_name = tool
        self.inputs = inputs
        self.max_retries = 0
        self.endpoint_url = "https://api.example.com/op"
        self.http_method = "GET"
        self.candidate_endpoints = []


class _Wave:
    def __init__(self, *tasks) -> None:
        self.tasks = list(tasks)
        self.wave = 0


def _tool_map() -> dict:
    return {
        "t1": {
            "id": str(uuid.uuid4()),
            "description": "d",
            "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"echo": {}}},
            "validation_rules": {},
            "auth_type": "none",
            "auth_ref": "",
            "cacheable": False,
            "idempotent": False,
            "enabled": True,
        }
    }


class TestExecutorDurableIdempotency:
    @pytest.fixture(autouse=True)
    def _no_db(self, monkeypatch):
        """Offline: neutralize the DB session factory + memory cache."""
        import nexus.memory.store as _ms

        class _NoSession:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr("nexus.db.async_session", lambda: _NoSession())
        monkeypatch.setattr(_ms.MemoryStore, "find_by_metadata", _noop_find)
        monkeypatch.setattr(_ms.MemoryStore, "put", _noop_put)

    def _executor(self, store, session_id="s1"):
        from nexus.agent.executors.concurrent_executor import ConcurrentExecutor

        return ConcurrentExecutor(
            tool_executor=_FakeToolExecutor(),
            tool_map=_tool_map(),
            session_id=session_id,
            ledger=CompletedExecutionLedger(store=store),
        )

    def test_duplicate_key_in_one_wave_executes_once(self):
        store = FakeLedgerStore()
        ex = self._executor(store)
        t1a = _Task("a", "t1", {"city": "Tokyo"})
        t1b = _Task("b", "t1", {"city": "Tokyo"})
        results = asyncio.run(
            ex.execute(
                tasks=[t1a, t1b],
                waves=[_Wave(t1a, t1b)],
                per_tool_timeout=5,
                global_timeout=30,
            )
        )
        assert len(ex._executor.calls) == 1, "duplicate keys must execute once"
        assert all(r.status == "success" for r in results.by_task.values())

    def test_fresh_executor_replays_via_ledger(self):
        """Reflection-style: a NEW executor instance (fresh in-memory
        completed-keys) must replay the completed result, not re-execute."""
        store = FakeLedgerStore()
        ex1 = self._executor(store)
        t1a = _Task("a", "t1", {"city": "Tokyo"})
        asyncio.run(
            ex1.execute(
                tasks=[t1a],
                waves=[_Wave(t1a)],
                per_tool_timeout=5,
                global_timeout=30,
            )
        )
        ex2 = self._executor(store)
        t2a = _Task("a", "t1", {"city": "Tokyo"})
        results = asyncio.run(
            ex2.execute(
                tasks=[t2a],
                waves=[_Wave(t2a)],
                per_tool_timeout=5,
                global_timeout=30,
            )
        )
        assert len(ex1._executor.calls) == 1
        assert len(ex2._executor.calls) == 0, "the second instance must replay"
        r = results.by_task["a"]
        assert r.status == "success"
        assert r.cached is True

    def test_different_inputs_execute_separately(self):
        store = FakeLedgerStore()
        ex = self._executor(store)
        t1a = _Task("a", "t1", {"city": "Tokyo"})
        t1b = _Task("b", "t1", {"city": "Osaka"})
        results = asyncio.run(
            ex.execute(
                tasks=[t1a, t1b],
                waves=[_Wave(t1a, t1b)],
                per_tool_timeout=5,
                global_timeout=30,
            )
        )
        assert len(ex._executor.calls) == 2
        assert all(r.status == "success" for r in results.by_task.values())

    def test_held_claim_returns_explicit_outcome(self):
        store = FakeLedgerStore()
        ex = self._executor(store)
        asyncio.run(ex._ledger.claim("s1", ex._compute_execution_key("t1", {"city": "Tokyo"}), "fp"))
        t1a = _Task("a", "t1", {"city": "Tokyo"})
        results = asyncio.run(
            ex.execute(
                tasks=[t1a],
                waves=[_Wave(t1a)],
                per_tool_timeout=5,
                global_timeout=30,
            )
        )
        r = results.by_task["a"]
        assert r.status == "error"
        assert "already in progress" in (r.error or "")
        assert len(ex._executor.calls) == 0, "a held claim must never double-execute"

    def test_definite_failure_releases_lease_for_immediate_retry(self):
        """A failed attempt must release its lease so the retry is
        immediately re-claimable (not blocked by a phantom 120s lease)."""
        store = FakeLedgerStore()

        class _FlakyTool(_FakeToolExecutor):
            def __init__(self) -> None:
                super().__init__()
                self.fail_first = True

            async def execute(self, tool, inputs, context, session, skip_approval=False):
                self.calls.append((tool.name, dict(inputs)))
                if self.fail_first:
                    self.fail_first = False
                    from nexus.tools.result import ToolResult

                    return ToolResult(
                        tool_id=uuid.uuid4(),
                        tool_name=tool.name,
                        status="error",
                        error="boom",
                        duration_ms=1,
                        http_status=500,
                    )
                return await super().execute(tool, inputs, context, session, skip_approval)

        tool_exec = _FlakyTool()
        ex1 = self._executor(store)
        ex1._executor = tool_exec
        t1a = _Task("a", "t1", {"city": "Tokyo"})
        r1 = asyncio.run(
            ex1.execute(
                tasks=[t1a],
                waves=[_Wave(t1a)],
                per_tool_timeout=5,
                global_timeout=30,
            )
        )
        assert r1.by_task["a"].status == "error"
        # Retry immediately with a fresh executor — must be re-claimable.
        ex2 = self._executor(store)
        ex2._executor = tool_exec
        t2a = _Task("a", "t1", {"city": "Tokyo"})
        r2 = asyncio.run(
            ex2.execute(
                tasks=[t2a],
                waves=[_Wave(t2a)],
                per_tool_timeout=5,
                global_timeout=30,
            )
        )
        assert r2.by_task["a"].status == "success", (
            "a definite failure must release the lease for immediate retry"
        )
        assert len(tool_exec.calls) >= 2, (
            "r1 executed (boom) and r2 re-claimed + executed (success)"
        )
        assert tool_exec.calls[-1][1] == {"city": "Tokyo"}


async def _noop_find(*a, **k):
    return []


async def _noop_put(*a, **k):
    return None


# ---------------------------------------------------------------------------
# D3 — global-timeout outcome merge (no silently missing data)
# ---------------------------------------------------------------------------


class _SlowToolExecutor(_FakeToolExecutor):
    def __init__(self, delay_s: float = 5.0) -> None:
        super().__init__()
        self._delay = delay_s

    async def execute(self, tool, inputs, context, session, skip_approval=False):
        await asyncio.sleep(self._delay)
        return await super().execute(tool, inputs, context, session, skip_approval)


class TestGlobalTimeoutOutcomeMerge:
    @pytest.fixture(autouse=True)
    def _no_db(self, monkeypatch):
        import nexus.memory.store as _ms

        class _NoSession:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr("nexus.db.async_session", lambda: _NoSession())
        monkeypatch.setattr(_ms.MemoryStore, "find_by_metadata", _noop_find)
        monkeypatch.setattr(_ms.MemoryStore, "put", _noop_put)

    def _executor(self, slow_executor):
        from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
        from nexus.execution.ledger import CompletedExecutionLedger

        return ConcurrentExecutor(
            tool_executor=slow_executor,
            tool_map=_tool_map(),
            session_id="s1",
            ledger=CompletedExecutionLedger(store=FakeLedgerStore()),
        )

    def test_inflight_uncertain_outcome_is_retained(self):
        """A global timeout must NOT report all-success with the in-flight
        task silently missing — its UNCERTAIN outcome reaches recovery."""
        slow = _SlowToolExecutor(delay_s=5.0)
        ex = self._executor(slow)
        t1 = _Task("a", "t1", {"city": "Tokyo"})
        results = asyncio.run(
            ex.execute(
                tasks=[t1],
                waves=[_Wave(t1)],
                per_tool_timeout=0.05,
                global_timeout=0.2,
            )
        )
        assert "a" in results.by_task, "the in-flight task's outcome must be retained"
        outcome = results.by_task["a"]
        assert outcome.status in ("uncertain", "timeout", "error"), outcome.status
        assert not results.successful, "a timed-out run must never be all-successful"

    def test_multiple_inflight_tasks_all_retained(self):
        slow = _SlowToolExecutor(delay_s=5.0)
        ex = self._executor(slow)
        t1 = _Task("a", "t1", {"city": "Tokyo"})
        t2 = _Task("b", "t1", {"city": "Osaka"})
        results = asyncio.run(
            ex.execute(
                tasks=[t1, t2],
                waves=[_Wave(t1, t2)],
                per_tool_timeout=0.05,
                global_timeout=0.2,
            )
        )
        assert {"a", "b"} <= set(results.by_task.keys()), (
            "every in-flight task must have an outcome"
        )
        assert not results.successful


