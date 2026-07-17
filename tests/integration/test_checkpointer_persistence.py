"""Test PostgresSaver checkpointer survives process restarts (HITL resume).

Uses a real PostgreSQL container via testcontainers. Runs Alembic migrations,
starts an agent run that hits a HITL interrupt, clears the in-memory graph
cache to simulate a process restart, then resumes from the Postgres checkpoints.
"""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool

from nexus.agent.graph import build_agent_graph
from nexus.agent.state import AgentState
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
        self.call_args: list[dict] = []

    async def complete(self, **kwargs: object) -> LLMResponse:
        self.call_count += 1
        self.call_args.append(kwargs)

        # 1: understand_intent
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
        # 2: plan — single step using requires_approval tool
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
        # 3: execute_step — ReAct calls tool→triggers HITL→interrupt
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
        # 4: after resume — analyze_results → finalize
        if self.call_count == 4:
            return _LLM.model_copy(
                update={
                    "content": json.dumps({
                        "outcome": "success",
                        "next_action": "finalize",
                        "reasoning": "Publish completed",
                    })
                }
            )
        # 5: finalize
        return _LLM.model_copy(update={"content": "Draft published successfully."})


@pytest_asyncio.fixture
async def pg_pool(postgres_container) -> AsyncConnectionPool:
    """Create a psycopg pool pointing at the test Postgres container."""
    raw_url = postgres_container.get_connection_url()
    pg_url = raw_url.replace("postgresql://", "postgresql+asyncpg://")
    os.environ["NEXUS_DATABASE__URL"] = pg_url

    pool_url = raw_url
    pool = AsyncConnectionPool(pool_url, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def checkpointer(pg_pool: AsyncConnectionPool) -> PostgresSaver:
    """Create a PostgresSaver connected via the pool."""
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
async def test_checkpointer_survives_restart(
    llm: MockLLM,
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
    checkpointer: PostgresSaver,
) -> None:
    """Verify PostgresSaver checkpointer allows resume after cache clear."""
    # ── Turn 1: Start graph, trigger HITL interrupt ──────────────────────
    graph = build_agent_graph(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        model="gpt-4o",
        checkpointer=checkpointer,
    )

    session_id = "test-persistence-session"
    thread_config = {"configurable": {"thread_id": session_id}}
    tid = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
    uid = str(uuid.uuid4())

    initial: AgentState = {
        "messages": [{"role": "user", "content": "Publish draft 42"}],
        "tenant_id": tid,
        "session_id": session_id,
        "user_id": uid,
        "user_context": {"id": uid},
        "plan": None,
        "current_step_index": 0,
        "gathered_requirements": {},
        "available_tools": [],
        "pending_approval": None,
        "iteration_count": 0,
        "scratchpad": "",
        "tool_results": [],
        "final_response": None,
        "intent": None,
        "missing_info_slots": None,
        "errors": [],
        "_routing_decision": "continue",
    }

    interrupted = False
    try:
        async for _event in graph.astream(initial, thread_config, stream_mode="updates"):
            pass
    except Exception:
        # Graph should interrupt for HITL — this is expected
        interrupted = True

    assert interrupted, "Graph should have interrupted for HITL approval"

    # Verify checkpoint was written
    state_snapshot = await graph.aget_state(thread_config)
    assert state_snapshot.next, "Graph should be paused (have next nodes)"
    assert state_snapshot.values.get("pending_approval") is not None, (
        "Should have pending_approval in state"
    )

    llm_call_count_turn1 = llm.call_count

    # ── Simulate process restart: discard graph, build fresh ─────────────
    # (No graph_cache.clear_all() needed — we never cache) 

    # ── Turn 2: Rebuild graph from Postgres checkpoints, resume ──────────
    graph2 = build_agent_graph(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        model="gpt-4o",
        checkpointer=checkpointer,
    )

    # Verify graph can load state from Postgres (not memory)
    new_snapshot = await graph2.aget_state(thread_config)
    assert new_snapshot.next, "After restart, graph should still be paused"
    assert new_snapshot.values.get("pending_approval") is not None, (
        "Pending approval should survive in Postgres checkpoints"
    )

    # Resume with approval
    final_response = None
    async for event in graph2.astream(
        Command(resume={"action": "approve"}),
        thread_config,
        stream_mode="updates",
    ):
        for _node_name, state_update in event.items():
            fr = state_update.get("final_response")
            if fr is not None:
                final_response = fr

    assert final_response is not None, "Graph should complete after approve"
    assert "published" in final_response.lower(), (
        f"Final response should mention publishing, got: {final_response}"
    )

    # Verify LLM was called additional times after resume
    assert llm.call_count > llm_call_count_turn1, (
        "LLM should be called more times after resume"
    )
