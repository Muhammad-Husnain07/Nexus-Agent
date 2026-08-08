"""Approval gate — dynamic HITL approval checks from tool metadata.

No hardcoded tool names or rules. Approval requirements are driven
entirely by each tool's ``risk_level`` and ``requires_approval`` fields.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("nexus.tools.approval_gate")


def requires_approval(tool_data: dict[str, Any]) -> bool:
    """Check if a tool requires human approval before execution.

    Dynamic — reads from tool metadata + settings. No hardcoded tool names.

    A tool requires approval if:
    - Its ``risk_level`` ranks at or above ``settings.tools.approval_min_risk``
      (compared via ``settings.agent.risk_order``), OR
    - Its ``requires_approval`` field is ``True``

    Args:
        tool_data: The tool metadata dict from ``available_tools``.

    Returns:
        True if the tool requires human approval.
    """
    risk_level = tool_data.get("risk_level", "low")
    explicit = tool_data.get("requires_approval", False)
    if explicit is True:
        return True
    try:
        from nexus.config.settings import get_settings as _ag_settings
        settings = _ag_settings()
        risk_order = settings.agent.risk_order
        min_risk = settings.tools.approval_min_risk
        return risk_order.get(risk_level, 0) >= risk_order.get(min_risk, 10_000)
    except Exception:
        return False


def check_plan_approval(
    tool_names: list[str],
    available_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Check which tools in a plan require approval.

    Args:
        tool_names: Tool names from the execution plan.
        available_tools: Full list of available tool definitions.

    Returns:
        List of tool data dicts that require approval (empty if none).
    """
    tool_map = {t.get("name", ""): t for t in available_tools if t.get("name")}
    pending: list[dict[str, Any]] = []
    for name in tool_names:
        tool = tool_map.get(name)
        if tool and requires_approval(tool):
            pending.append(tool)
    return pending


def format_approval_message(pending_tools: list[dict[str, Any]]) -> str:
    """Format a human-readable approval request message.

    Includes tool inputs when available (per-call approval scope).

    Args:
        pending_tools: List of tool data dicts requiring approval.
            Each entry has ``name`` and optionally ``inputs``, ``description``.

    Returns:
        A natural language message asking the user to approve or reject.
    """
    if not pending_tools:
        return ""

    parts = ["The following actions require your approval:"]
    for t in pending_tools:
        name = t.get("name", "unknown")
        desc = t.get("description", "") or t.get("purpose", "")
        risk = t.get("risk_level", "unknown")
        inputs = t.get("inputs", {})
        line = f"  - {name}: {desc} (risk: {risk})"
        if inputs:
            input_str = ", ".join(f"{k}={v}" for k, v in inputs.items())
            line += f" [{input_str}]"
        parts.append(line)
    parts.append("Reply with 'approve' to proceed or 'reject' to cancel.")
    return "\n".join(parts)
