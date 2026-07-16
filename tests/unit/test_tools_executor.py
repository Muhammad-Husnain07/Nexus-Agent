"""Unit tests for ToolExecutor — execute pipeline."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import SecretStr
from respx import MockRouter

from nexus.config.secrets import EnvSecretResolver
from nexus.config.settings import get_settings
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead


@pytest.fixture(autouse=True)
def _disable_hitl_default() -> None:
    """Disable global HITL default so tests can exercise the pipeline without
    every call triggering an ApprovalRequiredInterrupt."""
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"
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
        name="echo",
        description="Echoes back the input",
        purpose="Testing",
        endpoint_url="http://localhost:9999/echo",
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
        tags=["test"],
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


class TestExecuteSuccess:
    async def test_execute_returns_tool_result(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        route = respx_mock.post(tool.endpoint_url).respond(
            status_code=200,
            json={"echo": "hello"},
        )

        result = await executor.execute(tool, {"msg": "hello"}, context, session)

        assert isinstance(result, ToolResult)
        assert result.status == "success"
        assert result.data == {"echo": "hello"}
        assert result.http_status == 200
        assert route.called


class TestInputValidation:
    async def test_missing_required_field(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
    ) -> None:
        result = await executor.execute(tool, {}, context, session)

        assert result.status == "validation_error"
        assert "Input validation failed" in (result.error or "")

    async def test_invalid_type(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
    ) -> None:
        result = await executor.execute(tool, {"msg": 42}, context, session)

        assert result.status == "validation_error"


class TestApprovalGate:
    @patch("nexus.tools.executor.check_approval_required")
    async def test_raises_interrupt_when_required(
        self,
        mock_check: MagicMock,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
    ) -> None:
        mock_check.return_value.required = True

        from nexus.tools.approval_gate import ApprovalRequiredInterrupt

        with pytest.raises(ApprovalRequiredInterrupt):
            await executor.execute(tool, {"msg": "hi"}, context, session)


class TestAuthResolve:
    async def test_auth_header_injected(
        self,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        tool.auth_type = "bearer"
        tool.auth_ref = "MY_API_KEY"

        route = respx_mock.post(tool.endpoint_url).respond(status_code=200, json={"echo": "ok"})

        eb = AsyncMock()
        eb.publish = AsyncMock()
        with patch.object(EnvSecretResolver, "resolve", return_value=SecretStr("test-key")):
            executor = ToolExecutor(event_bus=eb)
            result = await executor.execute(tool, {"msg": "ok"}, context, session)

        assert result.status == "success"
        assert route.called
        sent = route.calls.last.request.headers.get("Authorization")
        assert sent == "Bearer test-key"


class TestPersist:
    async def test_tool_execution_row_written(
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


class TestOutputValidation:
    async def test_output_validation_failure_soft_fails(
        self,
        executor: ToolExecutor,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        """Output schema mismatch returns validation_error but does not raise."""
        # Output schema expects {"echo": str} but response has wrong type
        respx_mock.post(tool.endpoint_url).respond(status_code=200, json={"echo": 42})

        result = await executor.execute(tool, {"msg": "hi"}, context, session)

        assert result.status == "validation_error"
        assert "Output validation" in (result.error or "")


class TestTimeout:
    async def test_timeout_returns_timeout_status(
        self,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
        respx_mock: MockRouter,
    ) -> None:
        """TimeoutException handled and returns ToolResult with timeout status."""
        exc = httpx.TimeoutException("Connection timed out")
        respx_mock.post(tool.endpoint_url).mock(side_effect=exc)

        eb = AsyncMock()
        eb.publish = AsyncMock()
        executor = ToolExecutor(event_bus=eb)

        result = await executor.execute(tool, {"msg": "hi"}, context, session)

        assert result.status == "timeout"
        assert "timed out" in (result.error or "").lower()
        # TimeoutException is retryable by default (max_attempts=3)
        assert result.retried is True


class TestSandbox:
    async def test_sandbox_blocks_disallowed_host(
        self,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
    ) -> None:
        """Sandbox raises SandboxBlockedError for host not in allowed_hosts."""
        from nexus.tools.sandbox import SandboxConfig

        eb = AsyncMock()
        eb.publish = AsyncMock()
        executor = ToolExecutor(
            event_bus=eb,
            sandbox_config=SandboxConfig(
                enabled=True,
                allowed_hosts=["trusted.com"],
            ),
        )

        result = await executor.execute(tool, {"msg": "hello"}, context, session)

        assert result.status == "error"
        assert "not in allowed_hosts" in (result.error or "")


class TestBodySizeLimit:
    async def test_body_too_large_returns_validation_error(
        self,
        tool: ToolRead,
        context: ExecutionContext,
        session: MagicMock,
    ) -> None:
        from nexus.tools.sandbox import SandboxConfig

        eb = AsyncMock()
        eb.publish = AsyncMock()
        executor = ToolExecutor(
            event_bus=eb,
            sandbox_config=SandboxConfig(
                enabled=True,
                max_request_bytes=10,  # very small limit
            ),
        )

        # Input body is ~20 bytes, larger than 10
        result = await executor.execute(tool, {"msg": "this is a long message"}, context, session)

        assert result.status == "validation_error"
        assert "exceeds max size" in (result.error or "")


class TestResponseHeaders:
    async def test_response_headers_captured(
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
            headers={"x-request-id": "req-001", "content-type": "application/json"},
        )

        result = await executor.execute(tool, {"msg": "ok"}, context, session)

        assert result.response_headers is not None
        assert result.response_headers["x-request-id"] == "req-001"
        assert result.response_headers["content-type"] == "application/json"
