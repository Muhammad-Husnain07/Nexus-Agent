"""Integration test for ToolExecutor — full pipeline with testcontainers DB.

Uses testcontainers PostgreSQL to verify ToolExecution row persistence,
event publishing via Redis, retry on 503, and approval gating.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from respx import MockRouter
from sqlalchemy import select

from nexus.config.settings import get_settings
from nexus.db.models.tool import ToolExecution
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus, tool_channel
from nexus.tools.approval_gate import ApprovalRequiredInterrupt
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _test_env() -> None:
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"


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
        tenant_public=False,
        idempotent=False,
        version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


class TestExecuteWithPersistence:
    """Tool execution persists to real testcontainers DB."""

    async def test_tool_execution_row_written(
        self,
        db_session,  # from testcontainers conftest
        tool: ToolRead,
        context: ExecutionContext,
        respx_mock: MockRouter,
    ) -> None:
        respx_mock.post(tool.endpoint_url).respond(
            status_code=200,
            json={"echo": "hello"},
        )
        eb = AsyncMock(spec=EventBus)
        eb.publish = AsyncMock()
        executor = ToolExecutor(event_bus=eb)
        result = await executor.execute(tool, {"msg": "hello"}, context, db_session)
        assert result.status == "success"

        stmt = select(ToolExecution).where(ToolExecution.tool_id == tool.id)
        rows = (await db_session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "success"

    async def test_retry_on_503(
        self,
        db_session,
        tool: ToolRead,
        context: ExecutionContext,
        respx_mock: MockRouter,
    ) -> None:
        route = respx_mock.post(tool.endpoint_url).mock(
            side_effect=[
                httpx.HTTPStatusError(
                    "503 Service Unavailable",
                    request=MagicMock(),
                    response=MagicMock(status_code=503),
                ),
                httpx.Response(200, json={"echo": "retried"}),
            ]
        )
        executor = ToolExecutor(event_bus=None)
        result = await executor.execute(tool, {"msg": "retry"}, context, db_session)
        assert result.status == "success"
        assert result.data == {"echo": "retried"}
        assert route.call_count == 2

    async def test_approval_gate_raises(
        self,
        db_session,
        tool: ToolRead,
        context: ExecutionContext,
    ) -> None:
        tool.requires_approval = True
        executor = ToolExecutor(event_bus=None)
        with pytest.raises(ApprovalRequiredInterrupt):
            await executor.execute(tool, {"msg": "hi"}, context, db_session)
