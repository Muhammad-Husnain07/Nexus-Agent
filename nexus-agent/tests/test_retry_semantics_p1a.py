"""A0/P1-A — F7 non-idempotent retry semantics (I12).

A 500 / timeout / transport failure on a non-idempotent operation is
ambiguous — the side effect may have fired. The executor retry loop, the
endpoint fallback, and the MCP transport retry must NEVER automatically
re-invoke a non-idempotent capability.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from nexus.tools.mcp_client import _mcp_retry_policy


class _Task:
    def __init__(self, tid: str, tool: str, max_retries: int = 2) -> None:
        self.id = tid
        self.tool_name = tool
        self.inputs = {"city": "Tokyo"}
        self.max_retries = max_retries
        self.endpoint_url = "https://api.example.com/op"
        self.http_method = "POST"
        self.candidate_endpoints = []


class _Wave:
    def __init__(self, *tasks) -> None:
        self.tasks = list(tasks)
        self.wave = 0


class _CountingTool:
    """Tool executor that always fails with a transient 500."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, tool, inputs, context, session, skip_approval=False):
        self.calls += 1
        from nexus.tools.result import ToolResult

        return ToolResult(
            tool_id=uuid.uuid4(),
            tool_name=tool.name,
            status="error",
            error="HTTP 500: boom",
            duration_ms=1,
            http_status=500,
        )


def _tool_map(idempotent: bool) -> dict:
    return {
        "t1": {
            "id": str(uuid.uuid4()),
            "description": "d",
            "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {}},
            "validation_rules": {},
            "auth_type": "none",
            "auth_ref": "",
            "cacheable": False,
            "idempotent": idempotent,
            "enabled": True,
        }
    }


class TestExecutorRetrySemantics:
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

    def _run(self, tool, idempotent: bool, task: _Task):
        from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
        from nexus.execution.ledger import CompletedExecutionLedger

        # inline fake ledger store
        class _Store:
            def __init__(self) -> None:
                self.rows = {}

            async def find(self, s, k):
                return None

            async def claim(self, s, k, t, lease_s, fp):
                return True

            async def complete(self, s, k, r, t):
                pass

            async def release(self, s, k, t):
                pass

        ex = ConcurrentExecutor(
            tool_executor=tool,
            tool_map=_tool_map(idempotent),
            session_id="s1",
            ledger=CompletedExecutionLedger(store=_Store()),
        )
        return asyncio.run(
            ex.execute(
                tasks=[task],
                waves=[_Wave(task)],
                per_tool_timeout=5,
                global_timeout=30,
            )
        )

    def test_non_idempotent_transient_500_is_never_retried(self):
        tool = _CountingTool()
        results = self._run(tool, idempotent=False, task=_Task("a", "t1", max_retries=2))
        assert tool.calls == 1, (
            "a 500 on a non-idempotent op is ambiguous — never auto-retried (F7/I12)"
        )
        assert results.by_task["a"].status == "error"

    def test_idempotent_transient_500_is_retried(self):
        tool = _CountingTool()
        self._run(tool, idempotent=True, task=_Task("a", "t1", max_retries=2))
        assert tool.calls > 1, "idempotent capabilities may retry transient errors"

    def test_non_idempotent_timeout_is_never_retried(self):
        class _SlowTool(_CountingTool):
            async def execute(self, tool, inputs, context, session, skip_approval=False):
                self.calls += 1
                await asyncio.sleep(30)

        tool = _SlowTool()
        task = _Task("a", "t1", max_retries=2)
        from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
        from nexus.execution.ledger import CompletedExecutionLedger

        class _Store:
            async def find(self, s, k):
                return None

            async def claim(self, s, k, t, lease_s, fp):
                return True

            async def complete(self, s, k, r, t):
                pass

            async def release(self, s, k, t):
                pass

        ex = ConcurrentExecutor(
            tool_executor=tool,
            tool_map=_tool_map(False),
            session_id="s1",
            ledger=CompletedExecutionLedger(store=_Store()),
        )
        results = asyncio.run(
            ex.execute(
                tasks=[task],
                waves=[_Wave(task)],
                per_tool_timeout=0.05,
                global_timeout=5,
            )
        )
        assert tool.calls == 1, "a timeout on a non-idempotent op must not retry"


class TestMcpRetrySemantics:
    def test_non_idempotent_policy_is_single_attempt(self):
        policy = _mcp_retry_policy(max_attempts=1)
        assert policy.stop.max_attempt_number == 1

    def test_idempotent_policy_keeps_configured_attempts(self):
        policy = _mcp_retry_policy(max_attempts=None)
        assert policy.stop.max_attempt_number == 3  # settings default

    def test_mcp_transport_failures_respect_idempotency(self):
        from nexus.tools.mcp_client import MCPClient

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise httpx.ConnectError("refused")

        client = MCPClient(
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
            )
        )
        # Non-idempotent: single transport attempt.
        asyncio.run(
            client.call_mcp_tool(
                "http://mcp.example.com", "charge", {"x": 1}, idempotent=False
            )
        )
        assert calls["n"] == 1, "non-idempotent MCP calls must not retry (F7/I12)"
        # Idempotent: retried.
        asyncio.run(
            client.call_mcp_tool(
                "http://mcp.example.com", "get", {"x": 1}, idempotent=True
            )
        )
        assert calls["n"] >= 3


async def _noop_find(*a, **k):
    return []


async def _noop_put(*a, **k):
    return None
