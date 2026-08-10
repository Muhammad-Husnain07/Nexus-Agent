"""A2/P1-A — cache isolation (I7).

The artifact-cache read paths are session-scoped by CENTRAL enforcement
(the store's session_scope parameter), not by caller discipline. Only
capabilities explicitly declaring ``validation_rules.cache_scope ==
"public"`` are exempt. Default = private.

Matrix: session A → session A ✅; session A → session B ❌ (SQL-level);
public → everyone ✅ (scope dropped).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest


class FakeResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params):
        self.executed.append((str(sql), dict(params)))
        return FakeResult([])


@pytest.fixture
def fake_store(monkeypatch):
    """MemoryStore with an injected fake session that records SQL."""
    from nexus.memory.store import MemoryStore

    session = FakeSession()
    monkeypatch.setattr(
        "nexus.memory.store.async_session", lambda: session,
    )
    store = MemoryStore()
    store._fake_session = session
    return store


class TestStoreScopeEnforcement:
    def test_session_scope_restricts_lookup(self, fake_store):
        asyncio.run(
            fake_store.find_by_metadata(
                {"execution_key": "k1", "tool": "t1"},
                kind="artifact",
                session_scope="session-a",
            )
        )
        sql, params = fake_store._fake_session.executed[0]
        assert "session_id = :scope" in sql
        assert params["scope"] == "session-a"

    def test_no_scope_keeps_unscoped_behavior(self, fake_store):
        asyncio.run(
            fake_store.find_by_metadata(
                {"execution_key": "k1", "tool": "t1"},
                kind="artifact",
            )
        )
        sql, _params = fake_store._fake_session.executed[0]
        assert "session_id = :scope" not in sql

    def test_kind_and_scope_combined(self, fake_store):
        asyncio.run(
            fake_store.find_by_metadata(
                {"execution_key": "k1", "tool": "t1", "normalized": "true"},
                kind="normalized_artifact",
                session_scope="session-b",
            )
        )
        sql, params = fake_store._fake_session.executed[0]
        assert "kind = :kind" in sql
        assert "session_id = :scope" in sql
        assert params["kind"] == "normalized_artifact"
        assert params["scope"] == "session-b"

    def test_cross_session_read_carries_scope_and_key(self, fake_store):
        """Session A's row cannot be found by session B — the store's
        session_scope clause makes the match structurally impossible:
        B's read carries B's scope AND the execution key."""
        from nexus.memory.store import MemoryStore

        asyncio.run(
            MemoryStore().find_by_metadata(
                {"execution_key": "k1", "tool": "t1"},
                kind="artifact",
                session_scope="session-b",
            )
        )
        sql, params = fake_store._fake_session.executed[-1]
        assert "session_id = :scope" in sql
        assert params["scope"] == "session-b"
        assert params["mfk_0"] == "execution_key"
        assert params["mfv_0"] == "k1"


class TestExecutorScopeThreading:
    @pytest.fixture(autouse=True)
    def _no_db(self, monkeypatch):
        import nexus.memory.store as _ms

        class _NoSession:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr("nexus.db.async_session", lambda: _NoSession())

        captured: dict = {}

        async def _capture_find(*a, **k):
            captured.update(k)
            return []

        async def _noop_put(*a, **k):
            return None

        monkeypatch.setattr(_ms.MemoryStore, "find_by_metadata", _capture_find)
        monkeypatch.setattr(_ms.MemoryStore, "put", _noop_put)
        monkeypatch.setattr(
            "nexus.memory.store.MemoryStore.find_by_metadata", _capture_find
        )
        self._captured = captured

    def _tool_map(self, cache_scope: str | None = None) -> dict:
        rules = {}
        if cache_scope:
            rules["cache_scope"] = cache_scope
        return {
            "t1": {
                "id": str(uuid.uuid4()),
                "description": "d",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
                "output_schema": {"type": "object", "properties": {}},
                "validation_rules": rules,
                "auth_type": "none",
                "auth_ref": "",
                "cacheable": True,
                "idempotent": False,
                "enabled": True,
            }
        }

    class _Task:
        def __init__(self, tid: str) -> None:
            self.id = tid
            self.tool_name = "t1"
            self.inputs = {"city": "Tokyo"}
            self.max_retries = 0
            self.endpoint_url = "https://api.example.com/op"
            self.http_method = "GET"
            self.candidate_endpoints = []

    class _Wave:
        def __init__(self, *tasks) -> None:
            self.tasks = list(tasks)
            self.wave = 0

    class _Tool:
        async def execute(self, tool, inputs, context, session, skip_approval=False):
            from nexus.tools.result import ToolResult

            return ToolResult(
                tool_id=uuid.uuid4(), tool_name=tool.name,
                status="success", data={"echo": inputs}, duration_ms=1,
                http_status=200,
            )

    def _run(self, tool_map, session_id="s1"):
        from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
        from nexus.execution.ledger import CompletedExecutionLedger

        class _Store:
            async def find(self, s, k):
                return None

            async def claim(self, s, k, t, lease_s, fp, agent_run_id=None):
                return True

            async def complete(self, s, k, r, t, agent_run_id=None):
                pass

            async def release(self, s, k, t):
                pass

        ex = ConcurrentExecutor(
            tool_executor=self._Tool(),
            tool_map=tool_map,
            session_id=session_id,
            ledger=CompletedExecutionLedger(store=_Store()),
        )
        t = self._Task("a")
        asyncio.run(
            ex.execute(tasks=[t], waves=[self._Wave(t)], per_tool_timeout=5, global_timeout=30)
        )

    def test_private_default_reads_are_session_scoped(self):
        self._run(self._tool_map())
        assert self._captured.get("session_scope") == "s1", (
            "a private (default) capability's cache read MUST be session-scoped (I7)"
        )

    def test_public_scope_drops_the_session_filter(self):
        self._run(self._tool_map(cache_scope="public"))
        assert self._captured.get("session_scope") is None, (
            "an operator-declared public capability may reuse across sessions"
        )

    def test_invocation_reuse_within_session_preserved(self):
        """Scenario-34 semantics: the SAME session reuses cached results
        across turns — session-scoping must not break intra-session reuse."""
        self._run(self._tool_map(), session_id="s1")
        self._run(self._tool_map(), session_id="s1")
        assert self._captured.get("session_scope") == "s1"
