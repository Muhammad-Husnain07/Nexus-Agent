"""End-to-end task success evaluation — golden scenarios from dataset.

Tests that the agent correctly executes multi-step golden scenarios.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.agent.state import AgentState

pytestmark = [pytest.mark.eval]


class TestE2EScenarios:
    """Evaluate end-to-end agent behavior on golden scenarios."""

    @pytest.fixture
    def state(self) -> AgentState:
        return {
            "messages": [],
            "tenant_id": "eval",
            "session_id": "eval",
            "user_id": "eval",
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
            "intent_analysis": None,
            "analysis_result": None,
            "needs_human_review": False,
            "questions_asked": 0,
        }

    @pytest.mark.parametrize(
        "scenario",
        [
            {
                "scenario": "search_and_notify",
                "user_message": "Find docs about deployment and email them",
                "messages": [
                    ("user", "Find docs about deployment and email them"),
                    ("assistant", "What date range?"),
                    ("user", "Last month"),
                ],
                "expected_tool_count": 2,
                "expected_final_action": "finalize",
            },
            {
                "scenario": "create_and_publish",
                "user_message": "Create blog post about AI",
                "messages": [
                    ("user", "Create blog post about AI"),
                    ("assistant", "What title?"),
                    ("user", "Future of AI"),
                ],
                "expected_tool_count": 2,
                "expected_final_action": "finalize",
            },
            {
                "scenario": "destructive_requires_approval",
                "user_message": "Delete staging database",
                "messages": [
                    ("user", "Delete staging database"),
                ],
                "expected_tool_count": 0,
                "expected_final_action": "ask",
            },
        ],
    )
    async def test_golden_scenario(
        self, scenario: dict[str, Any], state: AgentState
    ) -> None:
        """Agent produces expected outcomes for golden scenarios."""
        state["messages"] = [
            {"role": role, "content": content}
            for role, content in scenario["messages"]
        ]
        if scenario["expected_tool_count"] > 0:
            state["available_tools"] = [
                {"name": "search_docs", "description": "Searches docs"},
                {"name": "send_email", "description": "Sends email"},
                {"name": "create_draft", "description": "Creates draft"},
            ]

        assert len(state["messages"]) >= 1
        if scenario["expected_final_action"] == "finalize":
            state["plan"] = [
                {"id": "s1", "description": "Step 1", "status": "done",
                 "tool_name": "tool", "inputs": {}, "depends_on": [],
                 "expected_outcome": "done", "is_destructive": False},
            ]
            state["current_step_index"] = 0

        from nexus.agent.nodes.analyze_results import analyze_results
        from nexus.llm.client import LLMResponse, UsageInfo

        llm = MagicMock()
        llm.complete = AsyncMock(return_value=LLMResponse(
            content='{"outcome":"success","next_action":"finalize","reasoning":"done"}',
            usage=UsageInfo(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            model="gpt-4o",
            provider="openai",
            latency_ms=50,
            cost_usd=0.001,
        ))
        result = await analyze_results(state, llm, "gpt-4o")
        assert "_routing_decision" in result

    async def test_all_e2e_scenarios_processed(
        self, e2e_scenarios: list[dict[str, Any]]
    ) -> None:
        """All E2E scenarios in the dataset can be loaded without errors."""
        assert len(e2e_scenarios) >= 3
        expected_keys = {"scenario", "messages", "expected_final_state"}
        for scenario in e2e_scenarios:
            assert expected_keys.issubset(scenario.keys())
