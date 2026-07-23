"""review_final_answer node — interrupt for human approval of the final response.

Only fires when ``needs_human_review`` is true.  Otherwise routes to
``continue`` without pausing.  Supports approve / edit / reject.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent import feedback_interrupt, hitl
from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.review_final_answer")


async def review_final_answer(
    state: AgentState,
) -> dict[str, Any]:
    """Pause and ask for human approval of the final response.

    The response is displayed to the user with approve / edit / reject.

    Returns:
        Dict with ``_routing_decision``, ``final_response``, and
        optionally ``response_type`` to trigger a re-plan on reject.
    """
    if not state.get("needs_human_review", False):
        logger.info("review_final.skipped", reason="no_review_required")
        return {"_routing_decision": "continue"}

    final: str | None = state.get("final_response")
    if not final:
        return {"_routing_decision": "continue"}

    payload = hitl.build_interrupt_payload(
        interrupt_type="final_review",
        data={"response": final},
        question="Approve this response?",
    )

    logger.info("review_final.interrupt", response_length=len(final))
    decision = feedback_interrupt.interrupt_for_feedback(payload)

    action = decision.get("action", "approve")

    if action == "reject":
        return {
            "final_response": None,
            "_routing_decision": "revise",
        }

    if action == "edit":
        edited = decision.get("modifications")
        if edited is None:
            edited = decision.get("edited_response")
        if edited is None:
            edited = decision.get("edited_inputs")
        if edited is None:
            logger.warning("review_final.unrecognized_edit", decision_keys=list(decision.keys()))
            edited = final
        if isinstance(edited, dict):
            edited_text = edited.get("response") or edited.get("text") or final
        else:
            edited_text = str(edited)
        return {
            "final_response": edited_text,
            "_routing_decision": "continue",
        }

    return {"_routing_decision": "continue"}
