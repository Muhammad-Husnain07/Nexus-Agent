"""reflect_on_response node — adaptive self-scoring with convergence detection.

Evaluates the final response quality using an adaptive threshold based on
task difficulty, domain, and score trajectory. Supports multi-round refinement
with convergence-based early stopping and optional model escalation.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState
from nexus.config.settings import AdaptiveReflectionSettings, get_settings
from nexus.llm.client import LLMClient
from nexus.observability.tracing import get_tracer
from nexus.utils.json_extractor import JsonExtractor

logger = structlog.get_logger("nexus.agent.nodes.reflect_on_response")

_json_extractor = JsonExtractor()


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


def _compute_adaptive_threshold(
    config: AdaptiveReflectionSettings,
    task_difficulty: float | None,
    domain: str,
) -> float:
    """Compute dynamic acceptance threshold based on domain + difficulty.

    The threshold is:
      base = domain_base or config.base_threshold
      difficulty_bonus = task_difficulty * 0.1  (harder tasks need higher quality)
      final = min(0.95, base + difficulty_bonus)
    """
    domain_base = config.domain_thresholds.get(domain, config.base_threshold)
    difficulty = task_difficulty if task_difficulty is not None else 0.5
    difficulty_bonus = difficulty * 0.1
    return min(0.95, domain_base + difficulty_bonus)


def _get_escalated_model(state: AgentState, current_model: str) -> str | None:
    """Check if a fallback/escalation model is configured in state."""
    escalation_model = state.get("_escalation_model")
    if escalation_model and escalation_model != current_model:
        return escalation_model
    return None


def _format_reflection_history(history: list[dict[str, Any]]) -> str:
    """Format past reflection rounds as context for the LLM."""
    if not history:
        return ""
    parts: list[str] = ["<previous_reflections>"]
    for h in history[-3:]:
        r = h.get("round", "?")
        score = h.get("score", "?")
        fb = h.get("feedback", "")
        parts.append(f'<round index="{r}" score="{score}">{fb}</round>')
    parts.append("</previous_reflections>")
    return "\n".join(parts)


async def reflect_on_response(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Evaluate the final response using adaptive threshold.

    Decisions are based on:
    1. An adaptive threshold (domain + difficulty adjusted)
    2. Convergence detection (score plateau over N rounds)
    3. Cost budget (stop if exceeded)
    4. Optional model escalation after N rounds of non-improvement
    5. Reflection history injection for context (Reflexion-style)

    Returns:
        Dict with ``reflection_score``, ``reflection_feedback``,
        ``reflection_count``, ``reflection_history``, and
        ``_routing_decision``.
    """
    settings = get_settings().agent
    adapt = settings.adaptive_reflection
    max_rounds = settings.max_reflection_rounds
    reflection_count: int = state.get("reflection_count", 0)
    history: list[dict[str, Any]] = list(state.get("reflection_history", []))

    # Skip reflection for social/greeting responses
    if state.get("response_type") in ("greeting", "meta", "memory_query"):
        logger.info("reflect.skipped", reason=f"non_tool_response: {state.get('response_type')}")
        return {
            "reflection_score": 10.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count,
            "reflection_history": [],
            "_routing_decision": "finalize",
        }

    # Skip reflection when a tool was executed in this turn and succeeded
    if state.get("_tool_executed_in_turn"):
        logger.info("reflect.skipped", reason="tool_succeeded_in_turn")
        return {
            "reflection_score": 10.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count,
            "reflection_history": [],
            "_routing_decision": "finalize",
        }

    if max_rounds <= 0 or reflection_count >= max_rounds:
        logger.info("reflect.skipped", reason="max_rounds_reached" if reflection_count >= max_rounds else "disabled")
        return {
            "reflection_score": 10.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count,
            "reflection_history": [],
            "_routing_decision": "finalize",
        }

    # Check cost budget — accept best-so-far if exceeded
    current_cost: float = state.get("total_cost_usd", 0.0)
    if current_cost >= adapt.cost_budget_usd:
        logger.info("reflect.cost_budget_exceeded", cost=current_cost, budget=adapt.cost_budget_usd)
        return {
            "reflection_score": 10.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count,
            "reflection_history": [],
            "_routing_decision": "finalize",
        }

    final: str | None = state.get("final_response")
    if not final:
        return {
            "reflection_score": 10.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count,
            "reflection_history": [],
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

    # Compute adaptive threshold
    task_difficulty: float | None = state.get("task_difficulty")
    domain: str = state.get("response_type", "tool")
    threshold = _compute_adaptive_threshold(adapt, task_difficulty, domain)

    # Inject reflection history context (Reflexion-style)
    reflection_context = _format_reflection_history(history)
    # Try escalation model after N rounds of non-improvement
    current_model = model
    if reflection_count >= adapt.max_escalation_rounds:
        escalated = _get_escalated_model(state, model)
        if escalated:
            logger.info("reflect.escalating_model", from_model=model, to_model=escalated)
            current_model = escalated

    example_context = {
        "response_type": state.get("response_type", "tool"),
        "intent": query[:100],
    }

    system_prompt = prompt_manager.render_with_examples(
        "reflect_on_response",
        version="1.0",
        context=example_context,
        max_examples=2,
        max_mistakes=2,
    )

    user_content = (
        f"<original_request>{query}</original_request>\n"
        f"<response>{final}</response>\n"
        f"<tool_results>{json.dumps(results, indent=2)}</tool_results>\n"
        f"<errors>{json.dumps(errors)}</errors>"
    )
    if reflection_context:
        user_content = reflection_context + "\n" + user_content

    response = await llm.complete(
        model=current_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )

    content = _json_extractor.extract(response.content or "")
    try:
        parsed: dict[str, Any] = json.loads(content or "{}")
        score = float(parsed.get("score", 10))
        feedback = str(parsed.get("feedback", ""))
        needs_improvement = bool(parsed.get("needs_improvement", False))
        approach_issue = bool(parsed.get("approach_issue", False))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("reflect.parse_failed", error=str(exc), content=response.content)
        return {
            "reflection_score": 5.0,
            "reflection_feedback": "",
            "reflection_count": reflection_count + 1,
            "reflection_history": [],
            "_routing_decision": "finalize",
        }

    # Tracing span for reflection
    _span_reflect = get_tracer().start_span("agent.reflect")
    _span_reflect.set_attribute("agent.reflect.score", score)
    _span_reflect.set_attribute("agent.reflect.threshold", threshold)
    _span_reflect.set_attribute("agent.reflect.round", reflection_count + 1)
    _span_reflect.set_attribute("agent.reflect.domain", domain)

    new_round: dict[str, Any] = {
        "round": reflection_count + 1,
        "score": score,
        "feedback": feedback,
        "approach_issue": approach_issue,
        "threshold": threshold,
        "domain": domain,
    }

    logger.info(
        "reflect.completed",
        score=score,
        threshold=threshold,
        needs_improvement=needs_improvement,
        approach_issue=approach_issue,
        all_tools_failed=all_tools_failed,
        round=reflection_count + 1,
        history_len=len(history) + 1,
    )

    # Add working memory entry for reflection result
    try:
        from nexus.memory.working import WorkingMemory  # noqa: PLC0415
        wm = WorkingMemory.from_dict(state.get("working_memory"))
        wm.add(key="reflection", content=f"Score {score:.1f}: {feedback[:100]}",
               source="reflection", importance=score / 10.0,
               turn_id=reflection_count + 1)
        wm_update = wm.to_dict()
    except Exception:
        wm_update = state.get("working_memory", {"entries": []})

    # Close tracing span
    _span_reflect.end()

    # Convergence detection: check if score has plateaued
    all_scores = [h["score"] for h in history] + [score]
    if _is_converging(all_scores, adapt.convergence_delta, adapt.convergence_window):
        logger.info("reflect.converged", scores=all_scores, delta=adapt.convergence_delta)
        return {
            "reflection_score": score,
            "reflection_feedback": feedback,
            "reflection_count": reflection_count + 1,
            "reflection_history": [new_round],
            "working_memory": wm_update,
            "_routing_decision": "finalize",
        }

    # Adaptive decision: compare score to dynamic threshold
    # LLM score is 0-10, threshold is 0-1, normalize by dividing by 10
    normalized_score = score / 10.0
    if not needs_improvement and normalized_score >= threshold:
        return {
            "reflection_score": score,
            "reflection_feedback": feedback,
            "reflection_count": reflection_count + 1,
            "reflection_history": [new_round],
            "working_memory": wm_update,
            "_routing_decision": "finalize",
        }

    # If all tools failed (no data), route to clarification regardless
    if approach_issue or all_tools_failed:
        return {
            "reflection_score": score,
            "reflection_feedback": feedback,
            "reflection_count": reflection_count + 1,
            "reflection_history": [new_round],
            "working_memory": wm_update,
            "gathered_requirements": {
                "_reflection_issue": feedback or "Tools returned no data — user input may be incorrect"
            },
            "_routing_decision": "clarify",
        }

    return {
        "reflection_score": score,
        "reflection_feedback": feedback,
        "reflection_count": reflection_count + 1,
        "reflection_revisions": state.get("reflection_revisions", 0) + 1,
        "reflection_history": [new_round],
        "working_memory": wm_update,
        "_routing_decision": "revise_finalize",
    }


def _is_converging(
    scores: list[float],
    delta: float,
    window: int,
) -> bool:
    """Detect if score improvements have plateaued.

    Returns True if the last ``window`` consecutive score changes
    are all less than ``delta``.
    """
    if len(scores) < window + 1:
        return False
    recent_deltas = [abs(scores[i] - scores[i - 1]) for i in range(-window, 0)]
    return all(d < delta for d in recent_deltas)
