"""HITL (Human-in-the-Loop) — approval interrupt functions.

Provides the standard interrupt call for tool-approval scenarios and
the extended ``requires_approval`` check that covers tool flags, plan-step
destructiveness, risk level, global default, and tool-name patterns.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import structlog
from langgraph.types import interrupt

from nexus.agent.state import PlanStep
from nexus.config.settings import AgentSettings
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.agent.hitl")

ApprovalDecision = Literal["approve", "reject", "edit"]


def requires_approval(
    tool_read: ToolRead,
    plan_step: dict[str, Any] | PlanStep | None = None,
    settings: AgentSettings | None = None,
) -> bool:
    """Determine whether a tool call requires human approval.

    Approval is required if **any** of the following are true:

    * ``tool_read.requires_approval`` is ``True``.
    * ``plan_step.is_destructive`` is ``True``.
    * ``tool_read.risk_level`` is ``"medium"`` or ``"high"``.
    * ``settings.hitl_default`` is ``True`` (global HITL default).
    * The tool name matches any regex in ``settings.hitl_tool_patterns``.

    Returns:
        ``True`` if human approval should be requested.
    """
    if tool_read.requires_approval:
        return True

    step = (
        plan_step
        if isinstance(plan_step, dict)
        else (plan_step.model_dump(mode="json") if plan_step else {})
    )
    if step.get("is_destructive", False):
        return True

    if tool_read.risk_level in ("medium", "high"):
        return True

    if settings is None:
        from nexus.config.settings import get_settings

        settings = get_settings().agent

    if settings.hitl_default:
        return True

    return any(re.search(pattern, tool_read.name) for pattern in settings.hitl_tool_patterns)


def build_approval_payload(
    tool_read: ToolRead,
    plan_step: dict[str, Any] | PlanStep | None = None,
    func_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the standard approval payload for ``interrupt()``.

    The payload is a JSON-serialisable dict with the keys expected by the
    frontend and by ``api.py``'s SSE interrupt-event detection.
    """
    step_name: str | None = None
    step_desc: str | None = None
    destructive: bool = False
    if plan_step:
        if isinstance(plan_step, dict):
            step_name = plan_step.get("id")
            step_desc = plan_step.get("description")
            destructive = plan_step.get("is_destructive", False)
        else:
            step_name = plan_step.id
            step_desc = plan_step.description
            destructive = plan_step.is_destructive

    return {
        "type": "approval_required",
        "kind": "tool_approval",
        "tool_call": {
            "name": tool_read.name,
            "inputs": func_args or {},
        },
        "step": {
            "id": step_name,
            "description": step_desc or "",
            "is_destructive": destructive,
        },
        "question": f"Approve execution of '{tool_read.name}'?",
        "risk_level": tool_read.risk_level,
    }


def interrupt_for_approval(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Pause the graph for human approval of a tool call.

    Calls ``langgraph.types.interrupt(payload)`` and returns the resumed
    decision dict.  The decision is expected to have the shape:

    .. code-block:: python

        {"action": "approve" | "reject" | "edit",
         "edited_inputs": dict | None,
         "comment": str | None}

    Args:
        payload: The approval payload (see :func:`build_approval_payload`).

    Returns:
        The decision dict provided by the external caller on resume.
    """
    logger.info("hitl.interrupt_for_approval", tool=payload.get("tool_call", {}).get("name"))
    decision: dict[str, Any] = interrupt(payload)
    action = decision.get("action", "approve")
    return {
        "action": action,
        "edited_inputs": decision.get("edited_inputs") if action == "edit" else None,
        "comment": decision.get("comment"),
    }
