"""Unit tests for execute_step, select_and_bind_tools, and present_preview nodes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.agent.nodes.execute_step import _resolve_placeholders, execute_step
from nexus.agent.nodes.present_preview import present_preview
from nexus.agent.nodes.select_and_bind_tools import select_and_bind_tools
from nexus.agent.state import AgentState
from nexus.config.settings import AgentSettings
from nexus.llm.client import LLMClient, LLMResponse, UsageInfo
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

_LLM_TOOL_RESPONSE = LLMResponse(
    content="",
    tool_calls=[
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"arg1": "val1"}'},
        }
    ],
    usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    model="gpt-4o",
    provider="openai",
    latency_ms=100,
    cost_usd=0.001,
)

_BASE_STATE: AgentState = {
    "messages": [{"role": "user", "content": "do something"}],
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "session_id": "00000000-0000-0000-0000-000000000002",
    "user_id": "00000000-0000-0000-0000-000000000003",
    "plan": [
        {
            "id": "step_1",
            "description": "Test step",
            "tool_name": "test_tool",
            "inputs": {"arg1": "val1"},
            "status": "pending",
            "depends_on": [],
            "expected_outcome": "done",
            "is_destructive": False,
        }
    ],
    "current_step_index": 0,
    "gathered_requirements": {},
    "available_tools": [
        {
            "id": "00000000-0000-0000-0000-000000000010",
            "name": "test_tool",
            "description": "A test tool",
            "purpose": "testing",
            "endpoint_url": "http://test.local/api",
            "http_method": "POST",
            "auth_type": "none",
            "auth_ref": "",
            "input_schema": {"type": "object", "properties": {"arg1": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {}},
            "validation_rules": {},
            "examples": [],
            "tags": [],
            "category": "general",
            "requires_approval": False,
            "risk_level": "low",
            "enabled": True,
            "version": 1,
            "tenant_id": "00000000-0000-0000-0000-000000000001",
            "created_at": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
            "updated_at": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
            "metadata": {},
        }
    ],
    "pending_approval": None,
    "iteration_count": 1,
    "scratchpad": "",
    "tool_results": [],
    "final_response": None,
    "intent": {"intent": "test", "parameters": {}},
    "missing_info_slots": None,
    "errors": [],
    "_bound_tools": [],
    "_routing_decision": "continue",
    "intent_analysis": None,
    "analysis_result": None,
    "needs_human_review": False,
    "questions_asked": 0,
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
def executor() -> ToolExecutor:
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


class TestResolvePlaceholders:
    """_resolve_placeholders — ${...} substitution in step inputs."""

    def test_resolves_from_gathered(self) -> None:
        result = _resolve_placeholders(
            {"text": "Hello ${name}"},
            {"name": "World"},
            [],
        )
        assert result == {"text": "Hello World"}

    def test_keeps_missing_as_literal(self) -> None:
        result = _resolve_placeholders(
            {"text": "Hello ${unknown_key}"},
            {},
            [],
        )
        assert result == {"text": "Hello ${unknown_key}"}

    def test_keeps_user_email_as_literal(self) -> None:
        result = _resolve_placeholders(
            {"to": "${user.email}"},
            {},
            [],
        )
        # The code double-braces user.email so it survives str.format()
        assert result == {"to": "${{user.email}}"}

    def test_resolves_nested_dict_inputs(self) -> None:
        result = _resolve_placeholders(
            {"nested": {"key": "value_${x}"}},
            {"x": "42"},
            [],
        )
        assert result == {"nested": {"key": "value_42"}}

    def test_resolves_from_tool_results(self) -> None:
        result = _resolve_placeholders(
            {"draft_id": "${create_draft.draft_id}"},
            {},
            [{"tool_name": "create_draft", "data": {"draft_id": "abc-123"}}],
        )
        assert result == {"draft_id": "abc-123"}

    def test_preserves_non_string_values(self) -> None:
        result = _resolve_placeholders(
            {"count": 42, "enabled": True, "tags": ["a", "b"]},
            {},
            [],
        )
        assert result == {"count": 42, "enabled": True, "tags": ["a", "b"]}


class TestSelectAndBindTools:
    """select_and_bind_tools node — pre-filter tools."""

    async def test_binds_matching_tool(self) -> None:
        state = dict(_BASE_STATE)
        result = await select_and_bind_tools(state)
        assert len(result["_bound_tools"]) == 1
        assert result["_bound_tools"][0]["function"]["name"] == "test_tool"

    async def test_returns_empty_when_no_step(self) -> None:
        state = dict(_BASE_STATE)
        state["plan"] = None
        result = await select_and_bind_tools(state)
        assert result["_bound_tools"] == []
        assert result["_routing_decision"] == "finalize"

    async def test_returns_all_tools_when_no_tool_name(self) -> None:
        state = dict(_BASE_STATE)
        state["plan"] = [
            {
                "id": "step_1",
                "description": "General step",
                "tool_name": None,
                "inputs": None,
                "status": "pending",
                "depends_on": [],
                "expected_outcome": None,
                "is_destructive": False,
            }
        ]
        result = await select_and_bind_tools(state)
        assert len(result["_bound_tools"]) == 1  # one available tool


class TestExecuteStep:
    """execute_step node — ReAct micro-loop."""

    @patch("nexus.agent.hitl.requires_approval", return_value=False)
    async def test_returns_continue_on_success(
        self,
        mock_requires_approval: MagicMock,
        llm: LLMClient,
        executor: ToolExecutor,
        settings: AgentSettings,
    ) -> None:
        llm.complete.side_effect = [
            _LLM_TOOL_RESPONSE,               # first call: tool call
            _LLM_RESPONSE.model_copy(update={"content": "Done."}),  # break loop
        ]
        result = await execute_step(_BASE_STATE, llm, executor, "gpt-4o", settings)
        assert result["_routing_decision"] == "continue"
        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["tool_name"] == "test_tool"
        assert result["plan"][0]["status"] == "done"

    async def test_step_not_found_returns_finalize(
        self, llm: LLMClient, executor: ToolExecutor, settings: AgentSettings
    ) -> None:
        state = dict(_BASE_STATE)
        state["plan"] = []
        result = await execute_step(state, llm, executor, "gpt-4o", settings)
        assert result["_routing_decision"] == "finalize"

    async def test_missing_tool_reports_error(
        self, llm: LLMClient, executor: ToolExecutor, settings: AgentSettings
    ) -> None:
        state = dict(_BASE_STATE)
        state["plan"] = [
            {
                "id": "step_1",
                "description": "Missing tool step",
                "tool_name": "nonexistent_tool",
                "inputs": {},
                "status": "pending",
                "depends_on": [],
                "expected_outcome": None,
                "is_destructive": False,
            }
        ]
        result = await execute_step(state, llm, executor, "gpt-4o", settings)
        assert result["_routing_decision"] == "revise"
        assert "nonexistent_tool" in result["errors"][0]

    async def test_no_tool_call_sends_llm_response(
        self, llm: LLMClient, executor: ToolExecutor, settings: AgentSettings
    ) -> None:
        llm.complete.return_value = _LLM_RESPONSE.model_copy(
            update={"content": "I'll handle this step directly."}
        )
        state = dict(_BASE_STATE)
        state["plan"] = [
            {
                "id": "step_1",
                "description": "LLM-only step",
                "tool_name": None,
                "inputs": None,
                "status": "pending",
                "depends_on": [],
                "expected_outcome": None,
                "is_destructive": False,
            }
        ]
        result = await execute_step(state, llm, executor, "gpt-4o", settings)
        assert result["plan"][0]["status"] == "done"

    async def test_llm_correction_on_validation_failure(
        self, llm: LLMClient, executor: ToolExecutor, settings: AgentSettings
    ) -> None:
        """LLM provides invalid args, correction call fixes them, step succeeds."""
        tool_call_invalid = _LLM_TOOL_RESPONSE.model_copy(deep=True)
        tool_call_invalid.tool_calls[0]["function"]["arguments"] = json.dumps({"arg1": "val1"})

        fixed_json = json.dumps({"inputs": {"arg1": "val1", "arg2": "val2"}})

        llm.complete.side_effect = [
            tool_call_invalid,                     # ReAct: tool call with invalid args
            _LLM_RESPONSE.model_copy(              # Correction: returns fixed inputs
                update={"content": fixed_json}
            ),
            _LLM_RESPONSE.model_copy(              # ReAct: done after correction + execution
                update={"content": "Step complete."}
            ),
        ]

        state = dict(_BASE_STATE)
        # Stricter schema: requires arg2
        state["available_tools"] = [
            {**state["available_tools"][0], "input_schema": {
                "type": "object",
                "properties": {"arg1": {"type": "string"}, "arg2": {"type": "string"}},
                "required": ["arg2"],
            }}
        ]
        state["plan"][0]["inputs"] = {"arg1": "val1"}

        with patch("nexus.agent.hitl.requires_approval", return_value=False):
            result = await execute_step(state, llm, executor, "gpt-4o", settings)

        assert result["_routing_decision"] == "continue"
        assert len(result["tool_results"]) == 1
        assert result["plan"][0]["status"] == "done"

    async def test_error_recovery_retry(
        self, llm: LLMClient, executor: ToolExecutor, settings: AgentSettings
    ) -> None:
        """Executor raises once, error recovery returns retry, second attempt succeeds."""
        retry_payload = json.dumps(
            {"action": "retry", "modified_inputs": {"arg1": "retry_val"}}
        )
        llm.complete.side_effect = [
            _LLM_TOOL_RESPONSE,                    # ReAct: tool call
            _LLM_RESPONSE.model_copy(              # Error recovery: retry
                update={"content": retry_payload}
            ),
            _LLM_TOOL_RESPONSE,                    # ReAct: retry tool call
            _LLM_RESPONSE.model_copy(              # ReAct: done
                update={"content": "Step complete after retry."}
            ),
        ]

        executor.execute.side_effect = [
            Exception("Temporary failure"),
            ToolResult(
                tool_id="00000000-0000-0000-0000-000000000010",
                tool_name="test_tool",
                status="success",
                data={"result": "retry_ok"},
                duration_ms=10,
            ),
        ]

        with patch("nexus.agent.hitl.requires_approval", return_value=False):
            result = await execute_step(_BASE_STATE, llm, executor, "gpt-4o", settings)

        assert result["_routing_decision"] == "continue"
        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["status"] == "success"

    async def test_error_recovery_revise(
        self, llm: LLMClient, executor: ToolExecutor, settings: AgentSettings
    ) -> None:
        """Executor raises, error recovery returns revise, step returns revise decision."""
        revise_payload = json.dumps(
            {"action": "revise", "reasoning": "tool fundamentally wrong"}
        )
        llm.complete.side_effect = [
            _LLM_TOOL_RESPONSE,                    # ReAct: tool call
            _LLM_RESPONSE.model_copy(              # Error recovery: revise
                update={"content": revise_payload}
            ),
        ]

        executor.execute.side_effect = Exception("Fatal error")

        with patch("nexus.agent.hitl.requires_approval", return_value=False):
            result = await execute_step(_BASE_STATE, llm, executor, "gpt-4o", settings)

        assert result["_routing_decision"] == "revise"

    async def test_approval_flow_approve(
        self, llm: LLMClient, executor: ToolExecutor, settings: AgentSettings
    ) -> None:
        """Approval required → user approves → tool executes."""
        llm.complete.side_effect = [
            _LLM_TOOL_RESPONSE,
            _LLM_RESPONSE.model_copy(update={"content": "Approved and done."}),
        ]
        with (
            patch("nexus.agent.hitl.requires_approval", return_value=True),
            patch(
                "nexus.agent.hitl.interrupt_for_approval",
                return_value={"action": "approve"},
            ),
        ):
            result = await execute_step(_BASE_STATE, llm, executor, "gpt-4o", settings)

        assert result["_routing_decision"] == "continue"
        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["status"] == "success"

    async def test_approval_flow_reject(
        self, llm: LLMClient, executor: ToolExecutor, settings: AgentSettings
    ) -> None:
        """Approval required → user rejects → step skipped, routed to continue."""
        llm.complete.side_effect = [
            _LLM_TOOL_RESPONSE,
        ]
        with (
            patch("nexus.agent.hitl.requires_approval", return_value=True),
            patch(
                "nexus.agent.hitl.interrupt_for_approval",
                return_value={"action": "reject", "comment": "Not appropriate"},
            ),
        ):
            result = await execute_step(_BASE_STATE, llm, executor, "gpt-4o", settings)

        assert result["_routing_decision"] == "continue"
        assert "rejected" in result["errors"][0].lower()
        assert result["plan"][0]["status"] == "skipped"

    async def test_approval_flow_edit(
        self, llm: LLMClient, executor: ToolExecutor, settings: AgentSettings
    ) -> None:
        """Approval required → user edits inputs → executes with edited inputs."""
        llm.complete.side_effect = [
            _LLM_TOOL_RESPONSE,
            _LLM_RESPONSE.model_copy(update={"content": "Edited and done."}),
        ]
        with (
            patch("nexus.agent.hitl.requires_approval", return_value=True),
            patch(
                "nexus.agent.hitl.interrupt_for_approval",
                return_value={
                    "action": "edit",
                    "edited_inputs": {"arg1": "edited_val"},
                },
            ),
        ):
            result = await execute_step(_BASE_STATE, llm, executor, "gpt-4o", settings)

        assert result["_routing_decision"] == "continue"
        assert len(result["tool_results"]) == 1
        assert result["tool_results"][0]["status"] == "success"


class TestPresentPreview:
    """present_preview node — HITL interrupt."""

    async def test_continue_on_user_approval(self) -> None:
        state = dict(_BASE_STATE)
        state["tool_results"] = [
            {"tool_name": "test_tool", "status": "success", "data": {"result": "ok"}}
        ]
        fb_patch = patch(
            "nexus.agent.feedback_interrupt.interrupt_for_feedback",
            return_value={"action": "approve"},
        )
        with fb_patch:
            result = await present_preview(state)
        assert result["_routing_decision"] == "continue"

    async def test_finalize_on_user_stop(self) -> None:
        state = dict(_BASE_STATE)
        with patch(
            "nexus.agent.feedback_interrupt.interrupt_for_feedback",
            return_value={"action": "reject"},
        ):
            result = await present_preview(state)
        assert result["_routing_decision"] == "finalize"
        assert "rejected" in result["final_response"].lower()

    async def test_edit_action_rewinds_and_routes_revise(self) -> None:
        state = dict(_BASE_STATE)
        state["tool_results"] = [
            {"tool_name": "test_tool", "status": "success", "data": {"result": "draft"}}
        ]
        state["plan"][0]["inputs"] = {"text": "hello"}
        with patch(
            "nexus.agent.feedback_interrupt.interrupt_for_feedback",
            return_value={"action": "edit", "modifications": {"text": "hello world edited"}},
        ):
            result = await present_preview(state)
        assert result["_routing_decision"] == "revise"
        assert result["current_step_index"] == 0
        assert result["plan"][0]["inputs"]["text"] == "hello world edited"
        assert result["plan"][0]["status"] == "pending"
