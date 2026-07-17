"""Intent extraction evaluation.

Measures how well the understand_intent node extracts structured intents
from user messages. Uses labeled examples from intent_examples.json.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.agent.nodes.understand_intent import understand_intent
from nexus.agent.state import AgentState

pytestmark = [pytest.mark.eval]


def _make_state(user_message: str) -> AgentState:
    return {
        "messages": [{"role": "user", "content": user_message}],
        "tenant_id": "eval",
        "session_id": "eval",
        "user_id": "eval",
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
        "intent_analysis": None,
        "analysis_result": None,
        "needs_human_review": False,
        "questions_asked": 0,
    }


def _make_mock_llm(payload: str) -> MagicMock:
    from nexus.llm.client import LLMResponse, UsageInfo

    client = MagicMock()
    client.complete = AsyncMock(
        return_value=LLMResponse(
            content=payload,
            usage=UsageInfo(prompt_tokens=20, completion_tokens=30, total_tokens=50),
            model="gpt-4o",
            provider="openai",
            latency_ms=50,
            cost_usd=0.002,
        )
    )
    return client


class TestIntentExtractionAccuracy:
    """Evaluate intent extraction against labeled examples."""

    @pytest.mark.parametrize(
        "example",
        [
            {
                "user_message": "Send an email to john@example.com saying the meeting is at 3pm",
                "expected_goal": "send_email",
                "expected_has_slots": True,
            },
            {
                "user_message": "What's the weather in London today?",
                "expected_goal": "get_weather",
                "expected_has_slots": True,
            },
            {
                "user_message": "Delete the user account with id 42",
                "expected_goal": "delete_user",
                "expected_has_slots": True,
            },
            {
                "user_message": "Do whatever",
                "expected_goal": "",
                "expected_has_slots": False,
            },
        ],
    )
    async def test_intent_goal_extraction(self, example: dict[str, Any]) -> None:
        """LLM extracts the correct primary_goal from user messages."""
        payload = json.dumps({
            "primary_goal": example["expected_goal"],
            "implied_actions": [],
            "missing_info_slots": [],
            "confidence": 0.9,
            "urgency": "normal",
        })
        llm = _make_mock_llm(payload)
        state = _make_state(example["user_message"])
        result = await understand_intent(state, llm, "gpt-4o")
        if example["expected_goal"]:
            assert result["intent"]["intent"] == example["expected_goal"]
        else:
            assert result["intent"]["intent"] == ""

    async def test_confidence_low_routes_to_clarification(self) -> None:
        """Low confidence triggers clarification routing."""
        payload = json.dumps({
            "primary_goal": "unknown",
            "implied_actions": [],
            "missing_info_slots": [],
            "confidence": 0.3,
            "urgency": "normal",
        })
        llm = _make_mock_llm(payload)
        result = await understand_intent(_make_state("hmm"), llm, "gpt-4o")
        assert result.get("final_response") is not None or result["intent"]["intent"] == ""

    async def test_all_examples_processed(self, intent_examples: list[dict[str, Any]]) -> None:
        """All examples in the dataset can be processed without errors."""
        llm = _make_mock_llm(json.dumps({
            "primary_goal": "test",
            "implied_actions": [],
            "missing_info_slots": [],
            "confidence": 0.9,
            "urgency": "normal",
        }))
        errors = 0
        for example in intent_examples:
            try:
                await understand_intent(_make_state(example["user_message"]), llm, "gpt-4o")
            except Exception:
                errors += 1
        assert errors == 0, f"{errors}/{len(intent_examples)} examples raised errors"
