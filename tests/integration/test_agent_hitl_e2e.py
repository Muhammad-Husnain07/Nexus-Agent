"""E2E tests for the HITL approval flow via middleware and execute_step.

Tests simulate the full approval lifecycle:
- Approve: tool requires approval → user approves → tool executes
- Reject: tool requires approval → user rejects → ApprovalRejected raised → step skipped
- Edit: tool requires approval → user edits inputs → re-validated → executes with edits
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.errors import ApprovalRejected
from nexus.agent.hitl_middleware import HITLMiddleware
from nexus.config.settings import AgentSettings
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead


@pytest.fixture
def mock_executor() -> ToolExecutor:
    ex = MagicMock(spec=ToolExecutor)
    ex.execute = AsyncMock(
        return_value=ToolResult(
            tool_id="00000000-0000-0000-0000-000000000010",
            tool_name="test_tool",
            status="success",
            data={"result": "done"},
            duration_ms=10,
        ),
    )
    return ex


@pytest.fixture
def tool_read() -> ToolRead:
    return ToolRead(
        id="00000000-0000-0000-0000-000000000010",
        tenant_id="00000000-0000-0000-0000-000000000001",
        name="test_tool",
        description="A test tool",
        purpose="testing",
        endpoint_url="http://test.local/api",
        http_method="POST",
        auth_type="none",
        auth_ref="",
        input_schema={
            "type": "object",
            "properties": {
                "arg1": {"type": "string"},
                "arg2": {"type": "integer"},
            },
            "required": ["arg1"],
        },
        output_schema={"type": "object", "properties": {}},
        validation_rules={},
        examples=[],
        tags=[],
        category="general",
        requires_approval=False,
        risk_level="low",
        enabled=True,
        version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(
        tenant_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        session_id="00000000-0000-0000-0000-000000000003",
    )


@pytest.fixture
def middleware(mock_executor: ToolExecutor) -> HITLMiddleware:
    return HITLMiddleware(
        executor=mock_executor,
        settings=AgentSettings(hitl_default=True),
    )


class TestHITLApproveFlow:
    """Approve flow — tool requires approval → user approves → executes."""

    async def test_approve_executes_tool(
        self,
        middleware: HITLMiddleware,
        mock_executor: ToolExecutor,
        tool_read: ToolRead,
        context: ExecutionContext,
    ) -> None:
        with patch("nexus.agent.hitl.interrupt_for_approval", return_value={"action": "approve"}):
            result = await middleware.execute(
                tool_read=tool_read,
                plan_step={"id": "step_1", "is_destructive": False},
                func_args={"arg1": "hello"},
                context=context,
            )

        assert result.status == "success"
        assert result.data == {"result": "done"}
        mock_executor.execute.assert_awaited_once_with(
            tool_read,
            {"arg1": "hello"},
            context,
            skip_approval=True,
            session=None,
        )

    async def test_approve_no_approval_needed_bypasses_interrupt(
        self,
        middleware: HITLMiddleware,
        mock_executor: ToolExecutor,
        tool_read: ToolRead,
        context: ExecutionContext,
    ) -> None:
        middleware._settings = AgentSettings(hitl_default=False)
        with patch("nexus.agent.hitl.interrupt_for_approval") as mock_interrupt:
            result = await middleware.execute(
                tool_read=tool_read,
                plan_step={"id": "step_1", "is_destructive": False},
                func_args={"arg1": "bypass"},
                context=context,
            )

        assert result.status == "success"
        mock_interrupt.assert_not_called()
        mock_executor.execute.assert_awaited_once()


class TestHITLRejectFlow:
    """Reject flow — tool requires approval → user rejects → ApprovalRejected."""

    async def test_reject_raises_approval_rejected(
        self,
        middleware: HITLMiddleware,
        mock_executor: ToolExecutor,
        tool_read: ToolRead,
        context: ExecutionContext,
    ) -> None:
        with (
            patch(
                "nexus.agent.hitl.interrupt_for_approval",
                return_value={"action": "reject", "comment": "Not now"},
            ),
            pytest.raises(ApprovalRejected, match="Not now"),
        ):
            await middleware.execute(
                tool_read=tool_read,
                plan_step={"id": "step_1"},
                func_args={"arg1": "world"},
                context=context,
            )

        mock_executor.execute.assert_not_called()

    async def test_defaults_to_approve_on_unknown_action(
        self,
        middleware: HITLMiddleware,
        mock_executor: ToolExecutor,
        tool_read: ToolRead,
        context: ExecutionContext,
    ) -> None:
        with patch("nexus.agent.hitl.interrupt_for_approval", return_value={"action": "unknown"}):
            result = await middleware.execute(
                tool_read=tool_read,
                plan_step={"id": "step_1"},
                func_args={"arg1": "default"},
                context=context,
            )

        assert result.status == "success"
        mock_executor.execute.assert_awaited_once()


class TestHITLEditFlow:
    """Edit flow — tool requires approval → user edits inputs → validated + executed."""

    async def test_edit_applies_new_inputs(
        self,
        middleware: HITLMiddleware,
        mock_executor: ToolExecutor,
        tool_read: ToolRead,
        context: ExecutionContext,
    ) -> None:
        with patch(
            "nexus.agent.hitl.interrupt_for_approval",
            return_value={
                "action": "edit",
                "edited_inputs": {"arg1": "edited_val", "arg2": 42},
            },
        ):
            result = await middleware.execute(
                tool_read=tool_read,
                plan_step={"id": "step_1"},
                func_args={"arg1": "original"},
                context=context,
            )

        assert result.status == "success"
        mock_executor.execute.assert_awaited_once_with(
            tool_read,
            {"arg1": "edited_val", "arg2": 42},
            context,
            skip_approval=True,
            session=None,
        )

    async def test_edit_rejects_invalid_inputs(
        self,
        middleware: HITLMiddleware,
        mock_executor: ToolExecutor,
        tool_read: ToolRead,
        context: ExecutionContext,
    ) -> None:
        with (
            patch(
                "nexus.agent.hitl.interrupt_for_approval",
                return_value={
                    "action": "edit",
                    "edited_inputs": {"arg1": 123},
                },
            ),
            pytest.raises(ValueError, match="Edited inputs failed validation"),
        ):
            await middleware.execute(
                tool_read=tool_read,
                plan_step={"id": "step_1"},
                func_args={"arg1": "original"},
                context=context,
            )

        mock_executor.execute.assert_not_called()
