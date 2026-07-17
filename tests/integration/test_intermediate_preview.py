"""Integration test for the present_preview node — intermediate user feedback.

Tests that analyze_results can return next_action="preview", routing to the
present_preview node, which interrupts for user feedback (approve/reject),
and resumes correctly.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.agent.graph import build_agent_graph
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


class StepRecorder:
    """LLM that returns canned responses and records calls."""

    def __init__(self, analyze_action: str = "preview") -> None:
        self.call_count = 0
        self._analyze_action = analyze_action

    async def complete(self, **kwargs: object) -> LLMResponse:
        self.call_count += 1

        # 1: understand_intent
        if self.call_count == 1:
            return _LLM.model_copy(
                update={
                    "content": json.dumps({
                        "intent": "create draft",
                        "parameters": {},
                        "missing_info_slots": [],
                    })
                }
            )
        # 2: plan — two steps: create_draft then publish
        if self.call_count == 2:
            return _LLM.model_copy(
                update={
                    "content": json.dumps({
                        "steps": [
                            {
                                "id": "step_1",
                                "description": "Create a draft article",
                                "tool_name": "create_draft",
                                "inputs": {"topic": "AI trends"},
                                "depends_on": [],
                                "expected_outcome": "Draft created with content",
                                "is_destructive": False,
                            },
                            {
                                "id": "step_2",
                                "description": "Publish the draft",
                                "tool_name": "publish_draft",
                                "inputs": {"draft_id": "${step_1.result.id}"},
                                "depends_on": ["step_1"],
                                "expected_outcome": "Draft published",
                                "is_destructive": True,
                            },
                        ],
                        "rationale": "Create then publish",
                        "estimated_tool_calls": 2,
                        "reversible": False,
                        "needs_human_review": False,
                    })
                }
            )
        # 3: execute_step — ReAct tool call
        if self.call_count == 3:
            return _LLM.model_copy(
                update={
                    "content": "",
                    "tool_calls": [{
                        "id": "call_create_1",
                        "type": "function",
                        "function": {
                            "name": "create_draft",
                            "arguments": json.dumps({"topic": "AI trends"}),
                        },
                    }],
                }
            )
        # 4: analyze_results — preview (test configurable)
        if self.call_count == 4:
            return _LLM.model_copy(
                update={
                    "content": json.dumps({
                        "outcome": "success",
                        "next_action": self._analyze_action,
                        "reasoning": "Draft created, show user before publishing",
                    })
                }
            )
        # 5: present_preview → resume → analyze step_2
        if self.call_count == 5:
            return _LLM.model_copy(
                update={
                    "content": json.dumps({
                        "outcome": "success",
                        "next_action": "continue",
                        "reasoning": "Continue with next step",
                    })
                }
            )
        # 6+: remaining steps
        return _LLM.model_copy(update={"content": "Done."})


@pytest.fixture(autouse=True)
def _test_env() -> None:
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"
    os.environ["NEXUS_TOOLS__SANDBOX_ENABLED"] = "false"
    from nexus.config.settings import get_settings

    get_settings.cache_clear()


_DRAFT_TOOL = ToolRead(
    id="00000000-0000-0000-0000-000000000010",
    tenant_id="00000000-0000-0000-0000-000000000001",
    name="create_draft",
    description="Create a draft article",
    purpose="Content creation",
    endpoint_url="http://example.com/create",
    http_method="POST",
    auth_type="none",
    auth_ref="",
    input_schema={
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
        },
    },
    validation_rules={},
    examples=[],
    tags=["content"],
    category="writing",
    requires_approval=False,
    risk_level="low",
    enabled=True,
    tenant_public=False,
    idempotent=False,
    version=1,
    created_at="2026-01-01T00:00:00+00:00",
    updated_at="2026-01-01T00:00:00+00:00",
)


@pytest.fixture
def tool_selector() -> DynamicToolSelector:
    sel = MagicMock(spec=DynamicToolSelector)
    sel.select = AsyncMock(return_value=[_DRAFT_TOOL])
    return sel


@pytest.fixture
def tool_executor() -> ToolExecutor:
    ex = MagicMock(spec=ToolExecutor)
    ex.execute = AsyncMock(
        return_value=ToolResult(
            tool_id=str(_DRAFT_TOOL.id),
            tool_name="create_draft",
            status="success",
            data={"id": "draft_42", "title": "AI Trends", "content": "Article content..."},
            duration_ms=10,
        )
    )
    return ex


@pytest.mark.asyncio
async def test_preview_approve(
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
) -> None:
    """LLM returns next_action=preview, user approves, run continues."""
    llm = StepRecorder(analyze_action="preview")

    graph = build_agent_graph(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        model="gpt-4o",
    )

    session_id = "test-preview-approve"
    thread_config = {"configurable": {"thread_id": session_id}}
    tid = "00000000-0000-0000-0000-000000000001"
    uid = "00000000-0000-0000-0000-000000000002"

    initial = {
        "messages": [{"role": "user", "content": "Create a draft about AI"}],
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
        "_bound_tools": [],
        "intent_analysis": None,
        "analysis_result": None,
        "needs_human_review": False,
        "questions_asked": 0,
    }

    # Invoke until interrupt
    interrupted = False
    preview_data = None
    try:
        async for event in graph.astream(initial, thread_config, stream_mode="updates"):
            for node_name, state_update in event.items():
                if node_name == "present_preview":
                    interrupted = True
                    preview_data = state_update
    except Exception:
        pass

    assert interrupted, "Graph should have paused at present_preview for user feedback"
    assert preview_data is not None, "Should have preview data"

    # Verify the intermediate preview was surfaced
    pending = preview_data.get("pending_approval") or preview_data.get("final_response")
    assert pending is not None, "present_preview should produce output for the user"

    # Resume with approve
    from langgraph.types import Command

    final_response = None
    async for event in graph.astream(
        Command(resume={"action": "approve"}),
        thread_config,
        stream_mode="updates",
    ):
        for _node_name, state_update in event.items():
            fr = state_update.get("final_response")
            if fr is not None:
                final_response = fr

    assert final_response is not None, "Graph should complete after approval"


@pytest.mark.asyncio
async def test_preview_reject(
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
) -> None:
    """LLM returns next_action=preview, user rejects, run finalizes."""
    llm = StepRecorder(analyze_action="preview")

    graph = build_agent_graph(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        model="gpt-4o",
    )

    session_id = "test-preview-reject"
    thread_config = {"configurable": {"thread_id": session_id}}
    tid = "00000000-0000-0000-0000-000000000001"
    uid = "00000000-0000-0000-0000-000000000002"

    initial = {
        "messages": [{"role": "user", "content": "Create a draft about AI"}],
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
        "_bound_tools": [],
        "intent_analysis": None,
        "analysis_result": None,
        "needs_human_review": False,
        "questions_asked": 0,
    }

    try:
        async for _event in graph.astream(initial, thread_config, stream_mode="updates"):
            pass
    except Exception:
        pass

    # Resume with reject
    from langgraph.types import Command

    final_response = None
    async for event in graph.astream(
        Command(resume={"action": "reject"}),
        thread_config,
        stream_mode="updates",
    ):
        for _node_name, state_update in event.items():
            fr = state_update.get("final_response")
            if fr is not None:
                final_response = fr

    assert final_response is not None, "Graph should produce a response after rejection"
    assert "rejected" in final_response.lower() or "abandon" in final_response.lower() or "cancel" in final_response.lower(), (
        f"Response should mention rejection/cancellation, got: {final_response}"
    )
