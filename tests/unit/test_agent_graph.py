"""Unit tests for individual graph node functions.

Tests each node in isolation with mocked dependencies.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.agent.graph import (
    analyze_results,
    discover_tools,
    finalize,
    gather_requirements,
    plan,
    understand_intent,
)
from nexus.agent.state import AgentState
from nexus.config.settings import AgentSettings
from nexus.llm.client import LLMClient, LLMResponse, UsageInfo
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.result import ToolResult

_LLM_RESPONSE = LLMResponse(
    content="",
    usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    model="gpt-4o",
    provider="openai",
    latency_ms=100,
    cost_usd=0.001,
)

_MINIMAL_STATE: AgentState = {
    "messages": [{"role": "user", "content": "create and publish a draft"}],
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "session_id": "00000000-0000-0000-0000-000000000002",
    "user_id": "00000000-0000-0000-0000-000000000003",
    "plan": None,
    "current_step_index": 0,
    "gathered_requirements": {},
    "available_tools": [],
    "pending_approval": None,
    "iteration_count": 1,
    "scratchpad": "",
    "tool_results": [],
    "final_response": None,
    "intent": None,
    "missing_info_slots": None,
    "errors": [],
    "_bound_tools": [],
    "_routing_decision": "continue",
}


@pytest.fixture
def llm() -> LLMClient:
    client = MagicMock(spec=LLMClient)
    client.complete = AsyncMock(return_value=_LLM_RESPONSE)
    return client


@pytest.fixture
def settings() -> AgentSettings:
    return AgentSettings()


@pytest.fixture
def tool_selector() -> DynamicToolSelector:
    sel = MagicMock(spec=DynamicToolSelector)
    sel.select = AsyncMock(return_value=[])
    return sel


@pytest.fixture
def tool_executor() -> ToolExecutor:
    ex = MagicMock(spec=ToolExecutor)
    ex.execute = AsyncMock(
        return_value=ToolResult(
            tool_id="00000000-0000-0000-0000-000000000010",
            tool_name="mock_tool",
            status="success",
            data={"result": "ok"},
            duration_ms=10,
        )
    )
    return ex


class TestUnderstandIntent:
    """understand_intent node — parse user message into structured intent."""

    async def test_parses_intent(self, llm: LLMClient) -> None:
        payload = json.dumps(
            {
                "intent": "create draft",
                "parameters": {"title": "test"},
                "missing_info_slots": [],
            }
        )
        llm.complete.return_value = _LLM_RESPONSE.model_copy(update={"content": payload})
        result = await understand_intent(_MINIMAL_STATE, llm, "gpt-4o")
        assert result["intent"]["intent"] == "create draft"
        assert result["missing_info_slots"] == []

    async def test_detects_missing_info(self, llm: LLMClient) -> None:
        payload = json.dumps(
            {
                "intent": "publish",
                "parameters": {},
                "missing_info_slots": ["content"],
            }
        )
        llm.complete.return_value = _LLM_RESPONSE.model_copy(update={"content": payload})
        result = await understand_intent(_MINIMAL_STATE, llm, "gpt-4o")
        assert "content" in result["missing_info_slots"]

    async def test_empty_message_returns_none(self, llm: LLMClient) -> None:
        state = dict(_MINIMAL_STATE)
        state["messages"] = []
        result = await understand_intent(state, llm, "gpt-4o")
        assert result["intent"] is None
        assert result["missing_info_slots"] == []

    async def test_parse_failure_returns_empty(self, llm: LLMClient) -> None:
        llm.complete.return_value = _LLM_RESPONSE.model_copy(update={"content": "not json"})
        result = await understand_intent(_MINIMAL_STATE, llm, "gpt-4o")
        assert result["intent"]["intent"] == ""


class TestGatherRequirements:
    """gather_requirements node — ask clarifying questions."""

    async def test_asks_question_when_missing(self, llm: LLMClient) -> None:
        state = dict(_MINIMAL_STATE)
        state["missing_info_slots"] = ["content"]
        llm.complete.return_value = _LLM_RESPONSE.model_copy(
            update={"content": "Please provide the content."}
        )
        result = await gather_requirements(state, llm, "gpt-4o")
        assert result["final_response"] is not None
        fr_lower = result["final_response"].lower()
        assert "content" in fr_lower or "please" in fr_lower

    async def test_returns_none_when_no_missing(self, llm: LLMClient) -> None:
        state = dict(_MINIMAL_STATE)
        state["missing_info_slots"] = []
        result = await gather_requirements(state, llm, "gpt-4o")
        assert result["final_response"] is None


class TestDiscoverTools:
    """discover_tools node — find relevant tools."""

    async def test_returns_tool_list(self, tool_selector: DynamicToolSelector) -> None:
        tool_selector.select.return_value = []
        result = await discover_tools(_MINIMAL_STATE, tool_selector)
        assert result["available_tools"] == []


class TestPlanNode:
    """plan node — generate step list."""

    async def test_creates_steps(self, llm: LLMClient, settings: AgentSettings) -> None:
        llm.complete.return_value = _LLM_RESPONSE.model_copy(
            update={
                "content": json.dumps(
                    {
                        "steps": [
                            {
                                "id": "step_1",
                                "description": "Create draft",
                                "tool_name": "create_tool",
                                "inputs": {"text": "hello"},
                                "depends_on": [],
                            },
                            {
                                "id": "step_2",
                                "description": "Publish draft",
                                "tool_name": "publish_tool",
                                "inputs": {},
                                "depends_on": ["step_1"],
                            },
                        ]
                    }
                )
            }
        )
        result = await plan(_MINIMAL_STATE, llm, "gpt-4o", settings)
        assert len(result["plan"]) == 2
        assert result["plan"][0]["tool_name"] == "create_tool"
        assert result["plan"][1]["depends_on"] == ["step_1"]

    async def test_empty_steps_raises(self, llm: LLMClient, settings: AgentSettings) -> None:
        from nexus.agent.errors import PlanningError

        llm.complete.return_value = _LLM_RESPONSE.model_copy(
            update={"content": json.dumps({"steps": []})}
        )
        with pytest.raises(PlanningError, match="empty plan"):
            await plan(_MINIMAL_STATE, llm, "gpt-4o", settings)


def _make_step(id: str, status: str, tool: str | None = None) -> dict:
    return {
        "id": id,
        "status": status,
        "description": "x",
        "tool_name": tool,
        "inputs": {} if tool else None,
        "depends_on": [],
    }


class TestAnalyzeResults:
    """analyze_results node — review results and decide next action."""

    async def test_finalizes_when_done(self, llm: LLMClient) -> None:
        state = dict(_MINIMAL_STATE)
        state["plan"] = [_make_step("s1", "done")]
        state["current_step_index"] = 0
        result = await analyze_results(state, llm, "gpt-4o")
        assert result["_routing_decision"] == "finalize"

    async def test_continues_to_next_step(self, llm: LLMClient) -> None:
        state = dict(_MINIMAL_STATE)
        state["plan"] = [_make_step("s1", "done"), _make_step("s2", "pending")]
        state["current_step_index"] = 0
        result = await analyze_results(state, llm, "gpt-4o")
        assert result["_routing_decision"] == "continue"
        assert result["current_step_index"] == 1

    async def test_asks_llm_on_failure(self, llm: LLMClient) -> None:
        llm.complete.return_value = _LLM_RESPONSE.model_copy(
            update={"content": json.dumps({"decision": "revise", "reason": "try different tool"})}
        )
        state = dict(_MINIMAL_STATE)
        state["plan"] = [_make_step("s1", "failed", tool="tool")]
        state["current_step_index"] = 0
        result = await analyze_results(state, llm, "gpt-4o")
        assert result["_routing_decision"] == "revise"


class TestFinalize:
    """finalize node — compose final answer."""

    async def test_returns_summary(self, llm: LLMClient) -> None:
        llm.complete.return_value = _LLM_RESPONSE.model_copy(
            update={"content": "All steps completed successfully."}
        )
        state = dict(_MINIMAL_STATE)
        state["tool_results"] = [{"tool_name": "t1", "status": "success", "data": {"ok": True}}]
        result = await finalize(state, llm, "gpt-4o")
        assert result["final_response"] is not None
        assert "successfully" in result["final_response"] or "completed" in result["final_response"]

    async def test_returns_errors_when_no_results(self, llm: LLMClient) -> None:
        state = dict(_MINIMAL_STATE)
        state["errors"] = ["Tool failed"]
        result = await finalize(state, llm, "gpt-4o")
        assert "issues" in result["final_response"] or "Tool failed" in result["final_response"]
