"""Integration tests for ToolExecutor — full pipeline with respx-mocked endpoints.

Covers the acceptance criteria:
- ToolExecution row written
- Event published
- Retry on 503
- Approval gate raises interrupt on requires_approval=True
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from respx import MockRouter

from nexus.config.settings import get_settings
from nexus.tools.approval_gate import ApprovalRequiredInterrupt
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead


@pytest.fixture(autouse=True)
def _test_env() -> None:
    """Ensure HITL is disabled and sandbox is off for integration tests."""
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"
    os.environ["NEXUS_TOOLS__SANDBOX_ENABLED"] = "false"
    get_settings.cache_clear()


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        agent_run_id=uuid.uuid4(),
    )


@pytest.fixture
def tool() -> ToolRead:
    return ToolRead(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="integration-test-tool",
        description="Integration test tool",
        purpose="Testing",
        endpoint_url="http://integration-test.local/api/echo",
        http_method="POST",
        auth_type="none",
        auth_ref="",
        input_schema={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
        output_schema={"type": "object", "properties": {"echo": {"type": "string"}}},
        validation_rules={},
        examples=[],
        tags=["integration"],
        category="general",
        requires_approval=False,
        risk_level="low",
        enabled=True,
        version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def executor() -> ToolExecutor:
    eb = AsyncMock()
    eb.publish = AsyncMock()
    return ToolExecutor(event_bus=eb)


@pytest.fixture
def session() -> MagicMock:
    m = MagicMock()
    m.flush = AsyncMock()
    return m


class TestSuccess:
    """Happy path — verifies ToolResult, persistence, and event publishing."""

    async def test_execute_returns_tool_result(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        route = respx_mock.post(tool.endpoint_url).respond(status_code=200, json={"echo": "hello"})

        result = await executor.execute(tool, {"msg": "hello"}, context, session)

        assert isinstance(result, ToolResult)
        assert result.status == "success"
        assert result.data == {"echo": "hello"}
        assert result.http_status == 200
        assert result.duration_ms >= 0
        assert result.retried is False
        assert route.called

    async def test_persists_tool_execution_row(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        respx_mock.post(tool.endpoint_url).respond(status_code=200, json={"echo": "ok"})

        await executor.execute(tool, {"msg": "ok"}, context, session)

        session.add.assert_called_once()
        execution = session.add.call_args[0][0]
        assert execution.tool_id == tool.id
        assert execution.tenant_id == context.tenant_id
        assert execution.status == "success"

    async def test_publishes_event(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        respx_mock.post(tool.endpoint_url).respond(status_code=200, json={"echo": "ok"})

        await executor.execute(tool, {"msg": "ok"}, context, session)

        executor._event_bus.publish.assert_awaited_once()
        channel = executor._event_bus.publish.call_args[0][0]
        assert str(context.session_id) in channel
        event = executor._event_bus.publish.call_args[0][1]
        assert event["type"] == "tool_execution"
        assert event["tool_name"] == "integration-test-tool"
        assert event["status"] == "success"

    async def test_captures_response_headers(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        respx_mock.post(tool.endpoint_url).respond(
            status_code=200,
            json={"echo": "ok"},
            headers={"x-request-id": "abc-123", "content-type": "application/json"},
        )

        result = await executor.execute(tool, {"msg": "ok"}, context, session)

        assert result.response_headers is not None
        assert result.response_headers["x-request-id"] == "abc-123"


class TestRetry:
    """Retry behavior — 503 with recovery and exhaustion."""

    async def test_retries_on_503_then_succeeds(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        route = respx_mock.post(tool.endpoint_url).mock(
            return_value=httpx.Response(503),
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json={"echo": "recovered"}),
            ],
        )

        result = await executor.execute(tool, {"msg": "retry-me"}, context, session)

        assert result.status == "success"
        assert result.data == {"echo": "recovered"}
        assert result.retried is True
        # 2 calls made (1 failed, 1 succeeded)
        assert len(route.calls) == 2

    async def test_all_retries_exhausted_returns_error(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        route = respx_mock.post(tool.endpoint_url).respond(status_code=503)

        result = await executor.execute(tool, {"msg": "fail"}, context, session)

        assert result.status == "error"
        assert result.http_status == 503
        assert result.retried is True
        assert len(route.calls) == 3  # initial + 2 retries = max_attempts

    async def test_non_retryable_400_passthrough(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        route = respx_mock.post(tool.endpoint_url).respond(
            status_code=400, json={"error": "bad request"}
        )

        result = await executor.execute(tool, {"msg": "bad"}, context, session)

        assert result.status == "error"
        assert result.http_status == 400
        assert result.retried is False
        assert len(route.calls) == 1  # no retry on 400


class TestApprovalGate:
    """Approval gate — raises interrupt when required."""

    async def test_raises_interrupt_on_requires_approval(
        self,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        tool.requires_approval = True

        eb = AsyncMock()
        eb.publish = AsyncMock()
        executor = ToolExecutor(event_bus=eb)

        with pytest.raises(ApprovalRequiredInterrupt) as exc_info:
            await executor.execute(tool, {"msg": "need-approval"}, context, session)

        assert exc_info.value.tool_name == "integration-test-tool"
        assert exc_info.value.inputs == {"msg": "need-approval"}

    async def test_no_interrupt_when_not_required(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        tool.requires_approval = False
        respx_mock.post(tool.endpoint_url).respond(status_code=200, json={"echo": "ok"})

        result = await executor.execute(tool, {"msg": "ok"}, context, session)

        assert result.status == "success"
