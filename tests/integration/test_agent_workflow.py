"""Integration test for the full agent workflow.

Runs the compiled graph with mocked LLM responses and tool executor,
verifies the correct event sequence and final response.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph import StateGraph

from nexus.agent.graph import build_agent_graph
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMResponse, UsageInfo
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead


@pytest.fixture(autouse=True)
def _test_env() -> None:
    """Disable HITL and sandbox for integration tests."""
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"
    os.environ["NEXUS_TOOLS__SANDBOX_ENABLED"] = "false"
    get_settings.cache_clear()


_LLM = LLMResponse(
    content="",
    usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    model="gpt-4o",
    provider="openai",
    latency_ms=50,
    cost_usd=0.001,
)

_STEP1_RESULT = ToolResult(
    tool_id="00000000-0000-0000-0000-000000000010",
    tool_name="create_draft",
    status="success",
    data={"draft_id": "42", "content": "hello world"},
    duration_ms=15,
)

_STEP2_RESULT = ToolResult(
    tool_id="00000000-0000-0000-0000-000000000011",
    tool_name="publish_draft",
    status="success",
    data={"url": "https://example.com/42"},
    duration_ms=10,
)


class MockLLMClient:
    """LLMClient that returns canned responses based on the call count."""

    def __init__(self) -> None:
        self._call_count = 0

    async def complete(self, **kwargs: object) -> LLMResponse:
        self._call_count += 1

        if self._call_count == 1:
            return _LLM.model_copy(
                update={
                    "content": json.dumps(
                        {
                            "intent": "create and publish draft",
                            "parameters": {"text": "hello"},
                            "missing_info_slots": [],
                        }
                    )
                }
            )
        if self._call_count == 2:
            return _LLM.model_copy(
                update={
                    "content": json.dumps(
                        {
                            "steps": [
                                {
                                    "id": "step_1",
                                    "description": "Create draft",
                                    "tool_name": "create_draft",
                                    "inputs": {"text": "hello"},
                                    "depends_on": [],
                                },
                                {
                                    "id": "step_2",
                                    "description": "Publish draft",
                                    "tool_name": "publish_draft",
                                    "inputs": {"draft_id": "42"},
                                    "depends_on": ["step_1"],
                                },
                            ]
                        }
                    )
                }
            )
        if self._call_count == 3:
            return _LLM.model_copy(
                update={
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "create_draft",
                                "arguments": json.dumps({"text": "hello"}),
                            },
                        }
                    ],
                }
            )
        if self._call_count == 4:
            return _LLM.model_copy(update={"content": "Draft created. Moving on."})
        if self._call_count == 5:
            return _LLM.model_copy(
                update={
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "publish_draft",
                                "arguments": json.dumps({"draft_id": "42"}),
                            },
                        }
                    ],
                }
            )
        if self._call_count == 6:
            return _LLM.model_copy(update={"content": "Draft published. All done."})
        return _LLM.model_copy(update={"content": "Task completed successfully."})


@pytest.fixture
def llm() -> MockLLMClient:
    return MockLLMClient()


@pytest.fixture
def tool_selector() -> DynamicToolSelector:
    sel = MagicMock(spec=DynamicToolSelector)
    sel.select = AsyncMock(
        return_value=[
            ToolRead(
                id="00000000-0000-0000-0000-000000000010",
                tenant_id="00000000-0000-0000-0000-000000000001",
                name="create_draft",
                description="Create a text draft",
                purpose="Create draft content",
                endpoint_url="http://example.com/create",
                http_method="POST",
                auth_type="none",
                auth_ref="",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                output_schema={"type": "object", "properties": {"draft_id": {"type": "string"}}},
                validation_rules={},
                examples=[],
                tags=["draft"],
                category="content",
                requires_approval=False,
                risk_level="low",
                enabled=True,
                version=1,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            ),
            ToolRead(
                id="00000000-0000-0000-0000-000000000011",
                tenant_id="00000000-0000-0000-0000-000000000001",
                name="publish_draft",
                description="Publish a draft",
                purpose="Publish draft to production",
                endpoint_url="http://example.com/publish",
                http_method="POST",
                auth_type="none",
                auth_ref="",
                input_schema={"type": "object", "properties": {"draft_id": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"url": {"type": "string"}}},
                validation_rules={},
                examples=[],
                tags=["publish"],
                category="content",
                requires_approval=False,
                risk_level="medium",
                enabled=True,
                version=1,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            ),
        ]
    )
    return sel


@pytest.fixture
def tool_executor() -> ToolExecutor:
    ex = MagicMock(spec=ToolExecutor)

    async def _execute(**kwargs: object) -> ToolResult:
        tool: ToolRead = kwargs.get("tool")  # type: ignore[assignment]
        if tool and tool.name == "create_draft":
            return _STEP1_RESULT
        if tool and tool.name == "publish_draft":
            return _STEP2_RESULT
        return _STEP1_RESULT

    ex.execute = AsyncMock(side_effect=_execute)
    return ex


def _initial_state(user_message: str) -> AgentState:
    return {
        "messages": [{"role": "user", "content": user_message}],
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "session_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "00000000-0000-0000-0000-000000000003",
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
        "_bound_tools": [],
        "_routing_decision": "continue",
    }


async def test_agent_workflow_completes(
    llm: MockLLMClient,
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
) -> None:
    """Run a 2-step plan (create draft, publish) and verify final response."""
    graph: StateGraph = build_agent_graph(
        llm_client=llm,  # type: ignore[arg-type]
        tool_selector=tool_selector,
        tool_executor=tool_executor,
    )

    initial = _initial_state("create and publish a draft saying hello")
    config: dict[str, object] = {"configurable": {"thread_id": "test-session"}}

    events: list[str] = []
    final_response: str | None = None

    async for step in graph.astream(initial, config, stream_mode="updates"):
        node_name = next(iter(step))
        update: dict[str, object] | None = step[node_name]

        if update and "final_response" in update and update["final_response"] is not None:
            final_response = str(update["final_response"])

        events.append(node_name)

    assert "understand_intent" in events
    assert "discover_tools" in events
    assert "plan" in events
    assert "execute_step" in events
    assert "analyze_results" in events
    assert "finalize" in events
    assert final_response is not None, "Agent should produce a final response"
    assert tool_executor.execute.await_count >= 1, "ToolExecutor should have been called"


async def test_agent_workflow_handles_clarification(
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
) -> None:
    """When missing_info_slots is present, agent should ask a question."""

    class ClarifyLLM:
        _call_count = 0

        async def complete(self, **kwargs: object) -> LLMResponse:
            self._call_count += 1
            return _LLM.model_copy(
                update={
                    "content": json.dumps(
                        {
                            "intent": "publish",
                            "parameters": {},
                            "missing_info_slots": ["content", "title"],
                        }
                    )
                }
            )

    graph = build_agent_graph(
        llm_client=ClarifyLLM(),  # type: ignore[arg-type]
        tool_selector=tool_selector,
        tool_executor=tool_executor,
    )

    initial = _initial_state("publish something")
    config: dict[str, object] = {"configurable": {"thread_id": "test-clarify"}}

    final_response: str | None = None
    async for step in graph.astream(initial, config, stream_mode="updates"):
        node_name = next(iter(step))
        update: dict[str, object] | None = step[node_name]
        if update and "final_response" in update and update["final_response"] is not None:
            final_response = str(update["final_response"])

    assert final_response is not None, "Should ask a clarifying question"
    assert len(final_response) > 0
