"""plan node — generate a step-by-step plan via LLM structured output."""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent.errors import PlanningError
from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState, Plan
from nexus.config.settings import AgentSettings
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.plan")


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


async def plan(
    state: AgentState,
    llm: LLMClient,
    model: str,
    settings: AgentSettings,
) -> dict[str, Any]:
    """Generate a step-by-step plan using the ``plan`` prompt template.

    Parses the full ``Plan`` Pydantic model including rationale,
    estimated_tool_calls, reversible.  Flags ``needs_human_review`` if
    any step is destructive or the tool requires approval.

    Returns:
        Dict with ``plan``, ``current_step_index``, and ``needs_human_review``.

    Raises:
        PlanningError: If the LLM output cannot be parsed or is empty.
    """
    tools: list[dict[str, Any]] = state.get("available_tools", [])
    tool_descriptions = json.dumps(
        [{
            "name": t["name"],
            "description": t.get("description", ""),
            "requires_approval": t.get("requires_approval", False),
            "risk_level": t.get("risk_level", "low"),
        } for t in tools],
        indent=2,
    )
    intent: dict[str, Any] = state.get("intent") or {}
    gathered: dict[str, Any] = state.get("gathered_requirements", {})

    user_context = json.dumps(
        {
            "intent": intent,
            "gathered_requirements": gathered,
            "available_tools": tool_descriptions,
            "max_steps": settings.max_plan_steps,
        },
        indent=2,
    )

    system_prompt = prompt_manager.render(
        "plan",
        version="2.0",
        tool_descriptions=tool_descriptions,
    )

    response = await llm.complete(
        model=model,
        messages=[
            _openai_message("system", system_prompt),
            _openai_message("user", user_context),
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    try:
        parsed: dict[str, Any] = json.loads(response.content or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise PlanningError(f"Failed to parse plan from LLM output: {exc}") from None

    steps_raw: list[dict[str, Any]] = parsed.get("steps", [])
    if not steps_raw:
        raise PlanningError("LLM returned empty plan")

    steps: list[dict[str, Any]] = []
    has_destructive = False
    for s in steps_raw:
        step_dict = {
            "id": s.get("id", f"step_{len(steps) + 1}"),
            "description": s.get("description", ""),
            "tool_name": s.get("tool_name"),
            "inputs": s.get("inputs"),
            "status": "pending",
            "depends_on": s.get("depends_on", []),
            "expected_outcome": s.get("expected_outcome"),
            "is_destructive": s.get("is_destructive", False),
        }
        if step_dict["is_destructive"]:
            has_destructive = True
        # Check if the tool requires approval
        if step_dict["tool_name"]:
            for t in tools:
                if t["name"] == step_dict["tool_name"] and t.get("requires_approval", False):
                    has_destructive = True
                    break
        steps.append(step_dict)

    # Attempt to parse the full Plan model (rationale, estimated_tool_calls, reversible)
    try:
        plan_obj = Plan(
            rationale=parsed.get("rationale", ""),
            estimated_tool_calls=parsed.get("estimated_tool_calls", len(steps)),
            reversible=parsed.get("reversible", True),
            steps=[],  # steps stored as plain dicts in state
            needs_human_review=has_destructive,
        )
        needs_review = plan_obj.needs_human_review
    except Exception:
        needs_review = has_destructive

    logger.info(
        "plan.created",
        step_count=len(steps),
        needs_human_review=needs_review,
        rationale=parsed.get("rationale", "")[:100],
    )
    return {
        "plan": steps,
        "current_step_index": 0,
        "needs_human_review": needs_review,
    }
