"""Test HITL resume works across separate AgentRunner instances (simulating multi-worker).

Builds a graph with PostgresSaver, triggers a HITL interrupt via one
AgentRunner ("worker A"), then resumes via a completely separate
AgentRunner ("worker B") with the same checkpointer — proving state
survives without any in-memory cache.
"""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import AsyncConnectionPool

from nexus.agent.runner import AgentRunner
from nexus.llm.client import LLMResponse, UsageInfo
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead

pytestmark = [pytest.mark.integration]


_LLM = LLMResponse(
    content="",
    usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    model="gpt-4o",
    provider="openai",
    latency_ms=50,
    cost_usd=0.001,
)

_APPROVAL_TOOL = ToolRead(
    id=uuid.uuid4(),
    tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
    name="publish_draft",
    description="Publish a draft article",
    purpose="Content publishing",
    endpoint_url="http://example.com/publish",
    http_method="POST",
    auth_type="none",
    auth_ref="",
    input_schema={
        "type": "object",
        "properties": {"draft_id": {"type": "string"}},
        "required": ["draft_id"],
    },
    output_schema={"type": "object", "properties": {"url": {"type": "string"}}},
    validation_rules={},
    examples=[],
    tags=["content"],
    category="publishing",
    requires_approval=True,
    risk_level="high",
    enabled=True,
    tenant_public=False,
    idempotent=False,
    version=1,
    created_at="2026-01-01T00:00:00+00:00",
    updated_at="2026-01-01T00:00:00+00:00",
)


class MockLLM:
    """Canned LLM response sequence for a publish flow with HITL."""

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(self, **kwargs: object) -> LLMResponse:
        self.call_count += 1

        if self.call_count == 1:
            return _LLM.model_copy(
                update={
                    "content": json.dumps({
                        "intent": "publish draft",
                        "parameters": {"draft_id": "42"},
                        "missing_info_slots": [],
                    })
                }
            )
        if self.call_count == 2:
            return _LLM.model_copy(
                update={
                    "content": json.dumps({
                        "steps": [{
                            "id": "step_1",
                            "description": "Publish draft 42",
                            "tool_name": "publish_draft",
                            "inputs": {"draft_id": "42"},
                            "depends_on": [],
                            "expected_outcome": "Draft published",
                            "is_destructive": True,
                        }],
                        "rationale": "Single publish step",
                        "estimated_tool_calls": 1,
                        "reversible": False,
                        "needs_human_review": True,
                    })
                }
            )
        if self.call_count == 3:
            return _LLM.model_copy(
                update={
                    "content": "",
                    "tool_calls": [{
                        "id": "call_publish_1",
                        "type": "function",
                        "function": {
                            "name": "publish_draft",
                            "arguments": json.dumps({"draft_id": "42"}),
                        },
                    }],
                }
            )
        # Post-resume calls
        return _LLM.model_copy(update={"content": "Draft published successfully."})


@pytest_asyncio.fixture
async def pg_pool(postgres_container) -> AsyncConnectionPool:
    raw_url = postgres_container.get_connection_url()
    os.environ["NEXUS_DATABASE__URL"] = raw_url.replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    pool = AsyncConnectionPool(raw_url, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def checkpointer(pg_pool: AsyncConnectionPool) -> PostgresSaver:
    conn = await pg_pool.connection()
    saver = PostgresSaver(conn=conn)
    await saver.setup()
    return saver


@pytest.fixture
def llm() -> MockLLM:
    return MockLLM()


@pytest.fixture
def tool_selector() -> DynamicToolSelector:
    sel = MagicMock(spec=DynamicToolSelector)
    sel.select = AsyncMock(return_value=[_APPROVAL_TOOL])
    return sel


@pytest.fixture
def tool_executor() -> ToolExecutor:
    ex = MagicMock(spec=ToolExecutor)
    ex.execute = AsyncMock(
        return_value=ToolResult(
            tool_id=str(_APPROVAL_TOOL.id),
            tool_name="publish_draft",
            status="success",
            data={"url": "https://example.com/42"},
            duration_ms=15,
        )
    )
    return ex


@pytest.mark.asyncio
async def test_multi_worker_resume(
    llm: MockLLM,
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
    checkpointer: PostgresSaver,
) -> None:
    """Worker A triggers HITL, Worker B resumes — no shared in-memory cache."""
    session_id = "test-multi-worker-session"
    tid = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
    uid = str(uuid.uuid4())

    # ── Worker A: start run, trigger HITL interrupt ─────────────────────
    worker_a = AgentRunner(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        checkpointer=checkpointer,
    )

    interrupted = False
    async for event in worker_a.invoke(
        session_id=session_id,
        user_message="Publish draft 42",
        tenant_id=tid,
        user_id=uid,
        config={"configurable": {"thread_id": session_id}},
    ):
        if event.type == "approval_required":
            interrupted = True

    assert interrupted, "Worker A should have triggered HITL interrupt"

    # ── Worker B: separate instance, same checkpointer, resume ──────────
    worker_b = AgentRunner(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        checkpointer=checkpointer,
    )

    final_response = None
    async for event in worker_b.resume(
        session_id=session_id,
        resume_value={"action": "approve"},
    ):
        if event.type == "final_response":
            final_response = event.payload.get("text", "")

    assert final_response is not None, "Worker B should complete the run"
    assert "published" in final_response.lower(), (
        f"Response should mention publishing, got: {final_response}"
    )
