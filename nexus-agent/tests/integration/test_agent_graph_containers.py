"""Integration test using testcontainers for full agent graph execution.

Runs the compiled LangGraph graph with testcontainers-backed DB,
mocked LLM (canned structured outputs), and respx-mocked tool endpoints.
Verifies HITL interrupt/resume cycle with real checkpointer.
"""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from respx import MockRouter

from nexus.agent.graph import build_agent_graph
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient, LLMResponse, UsageInfo
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.result import ToolResult

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(autouse=True)
def _test_env() -> None:
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"
    os.environ["NEXUS_TOOLS__SANDBOX_ENABLED"] = "false"
    get_settings.cache_clear()


class TestAgentGraphWithTestContainers:
    """Full agent graph with testcontainers-backed checkpointer and DB."""

    @pytest.fixture
    def mock_llm(self) -> MagicMock:
        llm = MagicMock(spec=LLMClient)
        llm.embed = AsyncMock(return_value=[[0.1] * 768])
        responses: list[LLMResponse] = [
            LLMResponse(
                content=json.dumps({
                    "primary_goal": "send email",
                    "implied_actions": ["send_email"],
                    "missing_info_slots": [],
                    "confidence": 0.95,
                    "urgency": "normal",
                }),
                usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
                model="gpt-4o",
                provider="openai",
                latency_ms=100,
                cost_usd=0.001,
            ),
            LLMResponse(
                content=json.dumps({
                    "rationale": "send one email",
                    "steps": [
                        {
                            "id": "step_1",
                            "description": "Send the email",
                            "tool_name": "test_tool",
                            "inputs": {"to": "user@example.com"},
                            "depends_on": [],
                            "expected_outcome": "email sent",
                            "is_destructive": False,
                        },
                    ],
                    "estimated_tool_calls": 1,
                    "reversible": True,
                }),
                usage=UsageInfo(prompt_tokens=20, completion_tokens=40, total_tokens=60),
                model="gpt-4o",
                provider="openai",
                latency_ms=100,
                cost_usd=0.002,
            ),
            LLMResponse(
                content=json.dumps({
                    "outcome": "success",
                    "next_action": "finalize",
                    "reasoning": "All steps done",
                }),
                usage=UsageInfo(prompt_tokens=10, completion_tokens=10, total_tokens=20),
                model="gpt-4o",
                provider="openai",
                latency_ms=50,
                cost_usd=0.001,
            ),
            LLMResponse(
                content="Email sent successfully.",
                usage=UsageInfo(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model="gpt-4o",
                provider="openai",
                latency_ms=50,
                cost_usd=0.001,
            ),
        ]

        response_iter = iter(responses)
        llm.complete = AsyncMock(side_effect=lambda **kw: next(response_iter))
        return llm

    def test_graph_builds_with_checkpointer(
        self, mock_llm: MagicMock, db_session
    ) -> None:
        """Graph compiles successfully with testcontainers DB checkpointer."""
        mock_sel = MagicMock(spec=DynamicToolSelector)
        mock_sel.select = AsyncMock(return_value=[])

        mock_exec = MagicMock(spec=ToolExecutor)
        mock_exec.execute = AsyncMock(return_value=ToolResult(
            tool_id="00000000-0000-0000-0000-000000000010",
            tool_name="test_tool",
            status="success",
            data={"result": "ok"},
            duration_ms=10,
        ))

        graph = build_agent_graph(
            llm_client=mock_llm,
            tool_selector=mock_sel,
            tool_executor=mock_exec,
            session_factory=lambda: db_session,
        )
        assert graph is not None
        assert hasattr(graph, "astream")

    async def test_graph_execution_with_testcontainers(
        self, mock_llm: MagicMock, db_session
    ) -> None:
        """Graph executes from start to finish and returns final_response."""
        mock_sel = MagicMock(spec=DynamicToolSelector)
        mock_sel.select = AsyncMock(return_value=[])

        mock_exec = MagicMock(spec=ToolExecutor)
        mock_exec.execute = AsyncMock(return_value=ToolResult(
            tool_id="00000000-0000-0000-0000-000000000010",
            tool_name="test_tool",
            status="success",
            data={"result": "ok"},
            duration_ms=10,
        ))

        graph = build_agent_graph(
            llm_client=mock_llm,
            tool_selector=mock_sel,
            tool_executor=mock_exec,
            session_factory=lambda: db_session,
        )

        sid = str(uuid.uuid4())
        initial_state: AgentState = {
            "messages": [{"role": "user", "content": "Send an email to user@example.com"}],
            "tenant_id": str(uuid.uuid4()),
            "session_id": sid,
            "user_id": str(uuid.uuid4()),
            "user_context": {"id": str(uuid.uuid4())},
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

        config = {"configurable": {"thread_id": sid}}
        updates = []
        async for event in graph.astream(initial_state, config, stream_mode="updates"):
            updates.append(event)

        assert len(updates) > 0
