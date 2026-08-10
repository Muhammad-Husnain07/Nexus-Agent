"""P2-C OBSERVABILITY CHAIN gate — every execution attempt joins back to
its parent request and run WITHOUT log-text parsing.

The chain under test (all joins are persisted columns):

    request_id (invocation_outcomes)
        → agent_run_id (outcome + tool_execution + completed_executions
                        + artifact cache metadata)
        → execution_key (logical operation identity — tool_execution +
                         completed_executions; STABLE across retries)
        → retried (attempt dimension — the SAME operation key across
                   attempts; idempotency rows never key on attempt)
        → outcome/event

Adversarial cases:

1. ONE run id threads every store — the run id constructed into the
   executor appears, identical, in the ledger claim, the ledger complete,
   the tool-execution context, and the artifact-cache metadata.
2. Operation identity vs attempt: execution_key is stable while the
   attempt marker (retried) varies — the durable idempotency distinction
   is preserved in observability.
3. The ledger adapter forwards the run id to the store protocol.
4. Persistence writes the join columns into the ROW (never logs).
5. Model ↔ migration parity for the two new columns.
"""

from __future__ import annotations

import asyncio
import re
import uuid

import pytest

RUN_ID = "run-p2c-0001"


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
    def __init__(self, captured: dict) -> None:
        self._captured = captured

    async def execute(self, tool, inputs, context, session, skip_approval=False):
        from nexus.tools.result import ToolResult

        self._captured["contexts"].append(
            {
                "agent_run_id": context.agent_run_id,
                "execution_key": getattr(context, "execution_key", None),
            }
        )
        return ToolResult(
            tool_id=uuid.uuid4(), tool_name=tool.name,
            status="success", data={"echo": inputs}, duration_ms=1,
            http_status=200,
        )


class _LedgerStore:
    """Capturing fake for the LedgerStore protocol (P2-C forwarding)."""

    def __init__(self, captured: dict) -> None:
        self._captured = captured

    async def find(self, session_id: str, execution_key: str):
        return None

    async def claim(self, session_id, execution_key, token, lease_s, arch_fp, agent_run_id=None):
        self._captured["claims"].append(
            {"key": execution_key, "agent_run_id": agent_run_id}
        )
        return True

    async def complete(self, session_id, execution_key, result, token, agent_run_id=None):
        self._captured["completes"].append(
            {"key": execution_key, "agent_run_id": agent_run_id}
        )

    async def release(self, session_id, execution_key, token):
        pass


@pytest.fixture
def _capture_env(monkeypatch):
    captured = {"claims": [], "completes": [], "contexts": [], "writes": []}

    import nexus.memory.store as _ms

    class _NoSession:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("nexus.db.async_session", lambda: _NoSession())

    async def _capture_find(*a, **k):
        return []

    async def _capture_put(*a, **k):
        captured["writes"].append(k)
        return uuid.uuid4()

    monkeypatch.setattr(_ms.MemoryStore, "find_by_metadata", _capture_find)
    monkeypatch.setattr(_ms.MemoryStore, "put", _capture_put)
    return captured


def _run_executor(captured: dict):
    from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
    from nexus.execution.ledger import CompletedExecutionLedger

    executor = ConcurrentExecutor(
        tool_executor=_Tool(captured),
        tool_map={
            "t1": {
                "id": str(uuid.uuid4()),
                "description": "d",
                "input_schema": {"type": "object", "properties": {}},
                "output_schema": {"type": "object", "properties": {}},
                "validation_rules": {},
                "auth_type": "none",
                "auth_ref": "",
                "cacheable": True,
                "idempotent": False,
                "enabled": True,
            }
        },
        session_id="s-p2c",
        agent_run_id=RUN_ID,
        ledger=CompletedExecutionLedger(store=_LedgerStore(captured)),
    )
    t = _Task("task-1")
    asyncio.run(
        executor.execute(tasks=[t], waves=[_Wave(t)], per_tool_timeout=5, global_timeout=30)
    )


def test_one_run_id_threads_every_store(_capture_env):  # noqa: PT019 (value used via _run_executor)
    """The SAME run id must appear in the ledger claim, the ledger
    complete, the tool-execution context, and the artifact-cache metadata —
    the full persisted join from one source value."""
    _run_executor(_capture_env)
    # ledger claim + complete
    assert _capture_env["claims"]
    assert _capture_env["completes"]
    assert all(c["agent_run_id"] == RUN_ID for c in _capture_env["claims"])
    assert all(c["agent_run_id"] == RUN_ID for c in _capture_env["completes"])
    # tool-execution context
    assert all(c["agent_run_id"] == RUN_ID for c in _capture_env["contexts"])
    # artifact-cache metadata (normalized_artifact writes carry run_id)
    normalized = [
        w for w in _capture_env["writes"]
        if w.get("metadata", {}).get("normalized") == "true"
    ]
    assert normalized, "no normalized_artifact write captured"
    assert all(w["metadata"]["run_id"] == RUN_ID for w in normalized)


@pytest.mark.usefixtures("_capture_env")
def test_operation_identity_stable_attempt_marker_distinct():
    """execution_key is STABLE across attempts (the logical operation) —
    the retried flag is the attempt dimension. Observability preserves the
    durable idempotency distinction (operation identity ≠ attempt)."""
    from nexus.tools.executor import ExecutionContext

    ctx_a = ExecutionContext(session_id=uuid.uuid4(), agent_run_id=RUN_ID, execution_key="ek-stable-1")
    ctx_b = ExecutionContext(session_id=uuid.uuid4(), agent_run_id=RUN_ID, execution_key="ek-stable-1")
    assert ctx_a.execution_key == ctx_b.execution_key  # same operation
    # the retried marker lives on the RESULT row, never on the key
    assert "retried" not in vars(ctx_a)


def test_ledger_adapter_forwards_run_id():
    from nexus.execution.ledger import CompletedExecutionLedger

    captured = {"claims": [], "completes": []}
    store = _LedgerStore(captured)
    ledger = CompletedExecutionLedger(store=store)
    token = asyncio.run(ledger.claim("s", "ek-1", "arch-fp", agent_run_id=RUN_ID))
    assert token is not None
    asyncio.run(ledger.complete("s", "ek-1", {"ok": True}, token, agent_run_id=RUN_ID))
    assert captured["claims"][0]["agent_run_id"] == RUN_ID
    assert captured["completes"][0]["agent_run_id"] == RUN_ID


def test_ledger_adapter_backwards_compatible_without_run_id():
    """The adapter still works when no run id is available (degrade-safe)."""
    from nexus.execution.ledger import CompletedExecutionLedger

    captured = {"claims": [], "completes": []}
    ledger = CompletedExecutionLedger(store=_LedgerStore(captured))
    token = asyncio.run(ledger.claim("s", "ek-2", "arch-fp"))
    asyncio.run(ledger.complete("s", "ek-2", {"ok": True}, token))
    assert captured["claims"][0]["agent_run_id"] is None
    assert captured["completes"][0]["agent_run_id"] is None


def test_persist_writes_join_columns_to_the_row(monkeypatch):
    """The join columns land in the persisted ROW (ToolExecution), never in
    logs — the chain is queryable without log-text parsing."""
    from nexus.tools.executor import ExecutionContext, ToolExecutor

    added = []

    class _FakeSession:
        def add(self, obj):
            added.append(obj)

        async def flush(self):
            pass

        async def commit(self):
            pass

    tool = type("ToolRead", (), {"id": uuid.uuid4(), "name": "t1"})()
    result = type(
        "ToolResult",
        (),
        {
            "data": {"x": 1},
            "status": "success",
            "http_status": 200,
            "duration_ms": 5,
            "error": None,
            "retried": True,
        },
    )()
    ctx = ExecutionContext(
        session_id=uuid.uuid4(), agent_run_id=RUN_ID, execution_key="ek-row-1"
    )
    asyncio.run(
        ToolExecutor._persist_execution(_FakeSession(), tool, ctx, result, {"in": 1})
    )
    assert len(added) == 1
    row = added[0]
    assert str(row.agent_run_id) == RUN_ID
    assert row.execution_key == "ek-row-1"
    assert row.retried is True  # attempt marker on the row, not the key


def test_chain_source_is_the_state_invocation_id(monkeypatch):
    """The single source of the run id is AgentState._invocation_id: the
    outcome assembly (P2-B) and the executor wiring (P2-C) must both derive
    the SAME value from it."""
    monkeypatch.setattr("nexus.compiler.cache._registry_fingerprint", lambda: "rf")
    from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
    from nexus.observability.outcomes import InvocationOutcome

    state = {
        "session_id": "sess-c",
        "errors": [],
        "_invocation_id": RUN_ID,
        "tool_results": [],
        "_plan_validator_report": None,
        "_logical_workflow": None,
        "_execution_graph": None,
    }
    outcome = InvocationOutcome.from_state(state, 1, request_id="req-c")
    assert outcome.agent_run_id == RUN_ID
    # the executor is wired from the same state field (graph.py contract)
    executor = ConcurrentExecutor(
        session_id="sess-c", agent_run_id=state.get("_invocation_id")
    )
    assert executor._agent_run_id == RUN_ID


# ============================================================================
# Model ↔ migration parity for the P2-C columns
# ============================================================================

_P2C_COLUMNS = {
    ("tool_execution", "execution_key"),
    ("completed_executions", "agent_run_id"),
}


def test_p2c_model_and_migration_column_parity():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    model_src = (root / "src" / "nexus" / "db" / "models" / "tool.py").read_text(
        encoding="utf-8"
    )
    model_src += (
        root / "src" / "nexus" / "db" / "models" / "completed_execution.py"
    ).read_text(encoding="utf-8")
    migration = (
        root / "alembic" / "versions" / "c2d3e4f5a6b7_p2c_observability_chain.py"
    ).read_text(encoding="utf-8")
    for table, column in _P2C_COLUMNS:
        assert re.search(rf"{column}: Mapped", model_src), (
            f"{table}.{column} missing from model"
        )
        assert re.search(rf"'{column}'", migration), (
            f"{table}.{column} missing from migration"
        )
    # migration is reversible — downgrade drops exactly the same columns
    assert migration.count("drop_column") == 2
