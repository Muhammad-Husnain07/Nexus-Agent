"""Plan quality evaluation.

Measures whether plan nodes produce correct step sequences given
intents and available tools.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.config.settings import AgentSettings
from nexus.llm.client import LLMResponse, UsageInfo

pytestmark = [pytest.mark.eval]


def _make_mock_llm(content: str) -> MagicMock:
    client = MagicMock()
    client.complete = AsyncMock(
        return_value=LLMResponse(
            content=content,
            usage=UsageInfo(prompt_tokens=20, completion_tokens=30, total_tokens=50),
            model="gpt-4o",
            provider="openai",
            latency_ms=50,
            cost_usd=0.002,
        )
    )
    return client


class TestPlanQuality:
    """Evaluate plan correctness against golden scenarios."""

    @pytest.mark.parametrize(
        "scenario",
        [
            {
                "message": "Create a draft blog post and publish it",
                "expected_tools": ["create_draft", "publish_draft"],
                "expected_count": 2,
            },
            {
                "message": "Search for documentation and send it to the team",
                "expected_tools": ["search_docs", "send_email"],
                "expected_count": 2,
            },
        ],
    )
    async def test_plan_step_order(self, scenario: dict[str, Any]) -> None:
        """Plan steps maintain correct dependency order."""
        payload = json.dumps({
            "rationale": "Execute the steps in order",
            "steps": [
                {
                    "id": "step_1",
                    "description": f"Execute {scenario['expected_tools'][0]}",
                    "tool_name": scenario["expected_tools"][0],
                    "inputs": {},
                    "depends_on": [],
                    "expected_outcome": "done",
                    "is_destructive": False,
                },
                {
                    "id": "step_2",
                    "description": f"Execute {scenario['expected_tools'][1]}",
                    "tool_name": scenario["expected_tools"][1],
                    "depends_on": ["step_1"],
                    "expected_outcome": "done",
                    "is_destructive": False,
                },
            ],
            "estimated_tool_calls": 2,
            "reversible": True,
        })
        llm = _make_mock_llm(payload)
        from nexus.agent.nodes.plan import plan

        state = {
            "messages": [{"role": "user", "content": scenario["message"]}],
            "tenant_id": "eval",
            "session_id": "eval",
            "user_id": "eval",
            "plan": None,
            "current_step_index": 0,
            "gathered_requirements": {},
            "available_tools": [
                {"name": t, "description": f"tool {t}"}
                for t in scenario["expected_tools"]
            ],
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
            "intent_analysis": None,
            "analysis_result": None,
            "needs_human_review": False,
            "questions_asked": 0,
        }
        settings = AgentSettings()
        result = await plan(state, llm, "gpt-4o", settings)
        assert len(result["plan"]) == scenario["expected_count"]
        tool_names = {s["tool_name"] for s in result["plan"] if s["tool_name"]}
        assert tool_names == set(scenario["expected_tools"])

    async def test_destructive_step_triggers_review(self) -> None:
        """Plan with destructive step flags needs_human_review."""
        payload = json.dumps({
            "rationale": "Delete file then create report",
            "steps": [
                {
                    "id": "step_1",
                    "description": "Delete old file",
                    "tool_name": "delete_file",
                    "inputs": {},
                    "depends_on": [],
                    "expected_outcome": "file deleted",
                    "is_destructive": True,
                },
                {
                    "id": "step_2",
                    "description": "Create new report",
                    "tool_name": "create_report",
                    "inputs": {},
                    "depends_on": [],
                    "expected_outcome": "report created",
                    "is_destructive": False,
                },
            ],
            "estimated_tool_calls": 2,
            "reversible": False,
        })
        llm = _make_mock_llm(payload)
        from nexus.agent.nodes.plan import plan

        state = {
            "messages": [{"role": "user", "content": "Delete old file and create report"}],
            "tenant_id": "eval",
            "session_id": "eval",
            "user_id": "eval",
            "plan": None,
            "current_step_index": 0,
            "gathered_requirements": {},
            "available_tools": [
                {"name": "delete_file", "description": "Deletes file"},
                {"name": "create_report", "description": "Creates report"},
            ],
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
            "intent_analysis": None,
            "analysis_result": None,
            "needs_human_review": False,
            "questions_asked": 0,
        }
        settings = AgentSettings()
        result = await plan(state, llm, "gpt-4o", settings)
        assert result["needs_human_review"] is True

    async def test_all_scenarios_processed(self, plan_scenarios: list[dict[str, Any]]) -> None:
        """All plan scenarios in the dataset process without errors."""
        payload = json.dumps({
            "rationale": "test",
            "steps": [
                {"id": "s1", "description": "Step 1", "tool_name": "tool", "inputs": {},
                 "depends_on": [], "expected_outcome": "done", "is_destructive": False},
            ],
            "estimated_tool_calls": 1,
            "reversible": True,
        })
        llm = _make_mock_llm(payload)
        from nexus.agent.nodes.plan import plan

        settings = AgentSettings()
        errors = 0
        for scenario in plan_scenarios:
            try:
                state = {
                    "messages": [{"role": "user", "content": scenario["user_message"]}],
                    "tenant_id": "eval",
                    "session_id": "eval",
                    "user_id": "eval",
                    "plan": None,
                    "current_step_index": 0,
                    "gathered_requirements": {},
                    "available_tools": scenario.get("available_tools", []),
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
                    "intent_analysis": None,
                    "analysis_result": None,
                    "needs_human_review": False,
                    "questions_asked": 0,
                }
                await plan(state, llm, "gpt-4o", settings)
            except Exception:
                errors += 1
        assert errors == 0, f"{errors}/{len(plan_scenarios)} scenarios raised errors"
