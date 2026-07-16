"""discover_tools node — find relevant tools via DynamicToolSelector."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.tools.discovery import DynamicToolSelector

logger = structlog.get_logger("nexus.agent.nodes.discover_tools")


async def discover_tools(
    state: AgentState,
    selector: DynamicToolSelector,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Discover relevant tools for the user's intent.

    Queries ``DynamicToolSelector`` with the parsed intent or the latest
    user message, then stores the results in ``available_tools``.

    Returns:
        Dict with ``available_tools`` list of serialised ``ToolRead`` dicts.
    """
    tenant_id = uuid.UUID(state["tenant_id"])
    intent: dict[str, Any] = state.get("intent") or {}
    query: str = intent.get("intent", "") or state.get("messages", [{}])[-1].get("content", "")

    session = session_factory() if session_factory else None
    tools = await selector.select(session, tenant_id=tenant_id, message=query)
    tool_dicts: list[dict[str, Any]] = [t.model_dump(mode="json") for t in tools]

    logger.info("tools.discovered", count=len(tool_dicts), query=query[:50])
    return {"available_tools": tool_dicts}
