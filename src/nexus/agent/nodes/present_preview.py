"""present_preview node — interrupt for human feedback on intermediate results."""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.agent import feedback_interrupt
from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.present_preview")


def _format_result(raw_data: dict[str, Any] | None, tool_name: str | None) -> str:
    """Format tool result as a human-readable preview."""
    if not raw_data:
        return "*(no data to preview)*"
    if isinstance(raw_data, str):
        return raw_data
    try:
        formatted = json.dumps(raw_data, indent=2, default=str)
        if len(formatted) > 2000:
            formatted = formatted[:2000] + "\n... (truncated)"
        return formatted
    except (TypeError, ValueError):
        return str(raw_data)


async def present_preview(state: AgentState) -> dict[str, Any]:
    """Show intermediate result and interrupt for human feedback.

    Formats the tool result as a human-readable preview.  The external caller
    must resume with one of:
    - ``{"action": "approve"}`` — continue execution
    - ``{"action": "edit", "modifications": {...}}`` — apply user edits
    - ``{"action": "reject"}`` — abandon the step

    Returns:
        Dict with ``_routing_decision``, ``final_response``, and optionally
        ``updated_inputs`` if the user provided edits.
    """
    tool_results: list[dict[str, Any]] = state.get("tool_results", [])
    last = tool_results[-1] if tool_results else {}
    raw_data: dict[str, Any] | None = last.get("data")
    tool_name: str | None = last.get("tool_name")

    preview = _format_result(raw_data, tool_name)

    payload = {
        "type": "intermediate_preview",
        "tool_name": tool_name,
        "status": last.get("status"),
        "preview": preview,
        "options": ["approve", "edit", "reject"],
    }

    logger.info("present_preview.interrupt", tool_name=tool_name, preview_length=len(preview))
    decision = feedback_interrupt.interrupt_for_feedback(payload)

    action = decision.get("action", "approve")
    if action == "reject":
        return {
            "final_response": "Step rejected by user.",
            "_routing_decision": "finalize",
        }
    if action == "edit":
        modifications = decision.get("modifications") or decision.get("edited_inputs") or {}
        current_idx = state.get("current_step_index", 0)
        prev_idx = max(0, current_idx - 1)
        plan = list(state.get("plan") or [])
        if 0 <= prev_idx < len(plan):
            step = dict(plan[prev_idx])
            step_inputs = dict(step.get("inputs") or {})
            step_inputs.update(modifications)
            step["inputs"] = step_inputs
            step["status"] = "pending"
            plan[prev_idx] = step
        return {
            "plan": plan,
            "current_step_index": prev_idx,
            "final_response": "Applying user edits, re-executing step...",
            "_routing_decision": "revise",
        }

    return {"_routing_decision": "continue"}
