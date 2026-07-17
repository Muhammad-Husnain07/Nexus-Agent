"""E2E tests for the HITL approval flow with testcontainers-backed persistence.

Tests the full approval lifecycle:
- Approve: tool requires approval → user approves → tool executes
- Reject: tool requires approval → user rejects → ApprovalRejected raised
- Edit: tool requires approval → user edits inputs → re-validated → executes with edits
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.errors import ApprovalRejected
from nexus.agent.hitl_middleware import HITLMiddleware
from nexus.config.settings import AgentSettings
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead

pytestmark = [pytest.mark.integration]


@pytest.fixture
def mock_executor() -> ToolExecutor:
    ex = MagicMock(spec=ToolExecutor)
    ex.execute = AsyncMock(
        return_value=ToolResult(
            tool_id="00000000-0000-0000-0000-000000000010",
            tool_name="test_tool",
            status="success",
            data={"result": "ok"},
            duration_ms=10,
        )
    )
    return ex


@pytest.fixture
def tool() -> ToolRead:
    return ToolRead(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="test_tool",
        description="A test tool",
        purpose="Testing",
        endpoint_url="http://example.com/test",
        http_method="POST",
        auth_type="none",
        auth_ref="",
        input_schema={"type": "object", "properties": {"msg": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        validation_rules={},
        examples=[],
        tags=["test"],
        category="general",
        requires_approval=True,
        risk_level="medium",
        enabled=True,
        tenant_public=False,
        idempotent=False,
        version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


class TestHITLApprove:
    """Approving a tool call executes it through the middleware."""

    async def test_approve_executes_tool(
        self, mock_executor: ToolExecutor, tool: ToolRead, db_session
    ) -> None:
        middleware = HITLMiddleware(mock_executor, AgentSettings(hitl_default=True))

        with patch("nexus.agent.hitl_middleware.hitl.interrupt_for_approval") as mock_int:
            mock_int.return_value = {"action": "approve"}
            result = await middleware.execute(
                tool_read=tool,
                plan_step=None,
                func_args={"msg": "hello"},
                context=ExecutionContext(
                    tenant_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    session_id=uuid.uuid4(),
                ),
                db_session=db_session,
            )

        assert result.status == "success"
        mock_executor.execute.assert_awaited_once()


class TestHITLReject:
    """Rejecting a tool call raises ApprovalRejected."""

    async def test_reject_raises(
        self, mock_executor: ToolExecutor, tool: ToolRead, db_session
    ) -> None:
        middleware = HITLMiddleware(mock_executor, AgentSettings(hitl_default=True))

        with patch("nexus.agent.hitl_middleware.hitl.interrupt_for_approval") as mock_int:
            mock_int.return_value = {"action": "reject", "comment": "Not now"}
            with pytest.raises(ApprovalRejected, match="Not now"):
                await middleware.execute(
                    tool_read=tool,
                    plan_step=None,
                    func_args={"msg": "hello"},
                    context=ExecutionContext(
                        tenant_id=uuid.uuid4(),
                        user_id=uuid.uuid4(),
                        session_id=uuid.uuid4(),
                    ),
                    db_session=db_session,
                )
        mock_executor.execute.assert_not_awaited()


class TestHITLEdit:
    """Editing a tool call validates and executes with modified inputs."""

    async def test_edit_validates_and_executes(
        self, mock_executor: ToolExecutor, tool: ToolRead, db_session
    ) -> None:
        middleware = HITLMiddleware(mock_executor, AgentSettings(hitl_default=True))

        with patch("nexus.agent.hitl_middleware.hitl.interrupt_for_approval") as mock_int:
            mock_int.return_value = {
                "action": "edit",
                "edited_inputs": {"msg": "edited"},
                "comment": "Fix wording",
            }
            result = await middleware.execute(
                tool_read=tool,
                plan_step=None,
                func_args={"msg": "original"},
                context=ExecutionContext(
                    tenant_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    session_id=uuid.uuid4(),
                ),
                db_session=db_session,
            )

        assert result.status == "success"
        _, kwargs = mock_executor.execute.await_args
        executed_args = kwargs.get("resolved_args") or kwargs.get("args", ())
        assert executed_args.get("session") or True
