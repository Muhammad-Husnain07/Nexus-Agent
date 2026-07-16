"""select_and_bind_tools node — pre-filter tools for the current plan step."""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.select_and_bind_tools")


def _tool_to_openai_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert a ToolRead dict to OpenAI tool-call schema."""
    schema = tool.get("input_schema") or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": schema,
        },
    }


def _get_current_step(state: AgentState) -> dict[str, Any] | None:
    plan: list[dict[str, Any]] | None = state.get("plan")
    if not plan:
        return None
    idx: int = state.get("current_step_index", 0)
    if 0 <= idx < len(plan):
        return plan[idx]
    return None


async def select_and_bind_tools(state: AgentState) -> dict[str, Any]:
    """Pre-filter and bind tools relevant to the current plan step.

    If the current step specifies a ``tool_name``, only that tool is bound.
    Otherwise all available tools are returned as OpenAI function schemas.

    Returns:
        Dict with ``_bound_tools`` (list of OpenAI tool-call schemas) and
        optionally ``_routing_decision`` if no step exists.
    """
    step = _get_current_step(state)
    if step is None:
        return {"_bound_tools": [], "_routing_decision": "finalize"}

    tools: list[dict[str, Any]] = state.get("available_tools", [])
    step_tool_name: str | None = step.get("tool_name")

    if step_tool_name:
        bound = [t for t in tools if t["name"] == step_tool_name]
        if not bound:
            logger.warning("tool.not_found_for_step", tool=step_tool_name, step=step["id"])
    else:
        bound = tools  # no specific tool required

    schemas = [_tool_to_openai_schema(t) for t in bound]
    return {"_bound_tools": schemas}
