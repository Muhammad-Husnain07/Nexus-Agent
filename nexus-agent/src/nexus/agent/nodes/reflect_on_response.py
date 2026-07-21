"""reflect_on_response node — evaluate final response quality and route for improvement.

If the response scores below threshold, routes back to ``finalize`` (regenerate)
or ``understand_intent`` (full re-plan) based on whether the issue is wrong
approach or just poor wording.

Limits reflection rounds via ``max_reflection_rounds`` in agent settings.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.reflect_on_response")


def _msg_content(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    return str(getattr(msg, "content", "") or "")


def _last_user_query(state: AgentState) -> str:
    messages: list = list(state.get("messages", []))
    for m in reversed(messages):
        role = msg_role(m)
        if role == "user":
            return _msg_content(m)
    return ""


def msg_role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    role = str(getattr(msg, "type", ""))
    if role == "human":
        return "user"
    if role == "ai":
        return "assistant"
    return role


async def reflect_on_response(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Evaluate the final response and decide whether to improve it.

    Returns:
        Dict with ``reflection_score``, ``reflection_feedback``,
        ``reflection_count``, and ``_routing_decision``.
    """
    settings = get_settings().agent
    max_rounds = settings.max_reflection_rounds
    reflection_count: int = state.get("reflection_count", 0)

    # Skip reflection for social/greeting responses
    if state.get("response_type") in ("greeting", "meta", "memory_query"):
        logger.info("reflect.skipped", reason=f"non_tool_response: {state.get('response_type')}")
        return {
            "reflection_score": 10.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count,
            "_routing_decision": "finalize",
        }

    if max_rounds <= 0 or reflection_count >= max_rounds:
        logger.info("reflect.skipped", reason="max_rounds_reached" if reflection_count >= max_rounds else "disabled")
        return {
            "reflection_score": 10.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count,
            "_routing_decision": "finalize",
        }

    final: str | None = state.get("final_response")
    if not final:
        return {
            "reflection_score": 10.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count,
            "_routing_decision": "finalize",
        }

    query = _last_user_query(state)
    results: list[dict[str, Any]] = state.get("tool_results", [])
    errors: list[str] = state.get("errors", [])

    # Heuristic: if all tools returned errors or null data, force approach_issue
    all_tools_failed = bool(results) and all(
        r.get("data") is None or r.get("error")
        for r in results
    )

    system_prompt = prompt_manager.render("reflect_on_response", version="1.0")

    response = await llm.complete(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"<original_request>{query}</original_request>\n"
                    f"<response>{final}</response>\n"
                    f"<tool_results>{json.dumps(results, indent=2)}</tool_results>\n"
                    f"<errors>{json.dumps(errors)}</errors>"
                ),
            },
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    try:
        parsed: dict[str, Any] = json.loads(response.content or "{}")
        score = float(parsed.get("score", 10))
        feedback = str(parsed.get("feedback", ""))
        needs_improvement = bool(parsed.get("needs_improvement", False))
        approach_issue = bool(parsed.get("approach_issue", False))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("reflect.parse_failed", error=str(exc), content=response.content)
        return {
            "reflection_score": 10.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count + 1,
            "_routing_decision": "finalize",
        }

    logger.info(
        "reflect.completed",
        score=score,
        needs_improvement=needs_improvement,
        approach_issue=approach_issue,
        all_tools_failed=all_tools_failed,
        round=reflection_count + 1,
    )

    if not needs_improvement:
        return {
            "reflection_score": score,
            "reflection_feedback": feedback,
            "reflection_count": reflection_count + 1,
            "_routing_decision": "finalize",
        }

    # If all tools failed (no data), route to clarification regardless of LLM classification
    if approach_issue or all_tools_failed:
        return {
            "reflection_score": score,
            "reflection_feedback": feedback,
            "reflection_count": reflection_count + 1,
            "gathered_requirements": {"_reflection_issue": feedback or "Tools returned no data — user input may be incorrect"},
            "_routing_decision": "clarify",
        }

    return {
        "reflection_score": score,
        "reflection_feedback": feedback,
        "reflection_count": reflection_count + 1,
        "_routing_decision": "revise_finalize",
    }
