"""review_plan node — interrupt for human approval of the execution plan.

Only fires when ``needs_human_review`` is true (destructive steps or
requires_approval tools).  Otherwise routes to ``continue`` without
pausing.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent import feedback_interrupt, hitl
from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.review_plan")


async def review_plan(
    state: AgentState,
) -> dict[str, Any]:
    """Pause and ask for human approval of the generated plan.

    The plan is displayed to the user with approve / edit / reject options.

    Returns:
        Dict with ``_routing_decision`` and optionally updated ``plan``.
    """
    if not state.get("needs_human_review", False):
        logger.info("review_plan.skipped", reason="no_review_required")
        return {"_routing_decision": "continue"}

    plan: list[dict[str, Any]] | None = state.get("plan")
    if not plan:
        return {"_routing_decision": "continue"}

    payload = hitl.build_interrupt_payload(
        interrupt_type="plan_review",
        data={"plan": plan},
        question="Review the plan before execution?",
    )

    logger.info("review_plan.interrupt", step_count=len(plan))
    decision = feedback_interrupt.interrupt_for_feedback(payload)

    action = decision.get("action", "approve")

    if action == "reject":
        return {
            "final_response": "Plan rejected by user. Please describe what you'd like to do differently.",
            "needs_human_review": False,
            "_routing_decision": "finalize",
        }

    if action == "edit":
        modifications = decision.get("modifications") or decision.get("edited_inputs") or {}
        if modifications:
            plan = _apply_plan_edits(plan, modifications)
        return {"plan": plan, "_routing_decision": "continue"}

    return {"_routing_decision": "continue"}


def _apply_plan_edits(
    plan: list[dict[str, Any]],
    edits: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply user edits to a plan.

    Supports:
    - ``{"step_id": {"inputs": {...}, "tool_name": "..."}}`` — update specific step
    - ``{"steps": [...]}`` — full plan replacement
    """
    if "steps" in edits:
        return list(edits["steps"])

    updated = list(plan)
    for step in updated:
        step_id = step.get("id", "")
        if step_id in edits:
            step.update(edits[step_id])
    return updated
