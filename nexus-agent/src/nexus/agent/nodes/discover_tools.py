"""discover_tools node — find relevant tools via DynamicToolSelector."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from nexus.agent.nodes import msg_content
from nexus.agent.state import AgentState
from nexus.tools.discovery import DynamicToolSelector

logger = structlog.get_logger("nexus.agent.nodes.discover_tools")


async def discover_tools(
    state: AgentState,
    selector: DynamicToolSelector,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Discover relevant tools for the user's intent.

    Fast path: if the intent directly matches a tool name or purpose,
    return it immediately without semantic search.
    """
    intent: dict[str, Any] = state.get("intent") or {}
    query: str = intent.get("intent", "") or msg_content(state.get("messages", [{}])[-1])
    query_lower = query.lower()

    # Fast path: direct tool match by name or purpose
    pre_populated = state.get("available_tools", [])
    direct_matches = []
    for t in pre_populated:
        name = t.get("name", "").lower()
        purpose = t.get("purpose", "").lower()
        desc = t.get("description", "").lower()
        # Match if query contains the tool name (underscores as spaces) or
        # the tool purpose contains key intent words
        if name.replace("_", " ") in query_lower or any(
            word in purpose for word in query_lower.split() if len(word) > 3
        ) or any(word in desc for word in query_lower.split() if len(word) > 3):
            direct_matches.append(t)

    # Use pre-filtered tools from understand_intent if available (avoids
    # redundant semantic search).  The semantic filter runs alongside intent
    # parsing and uses the same embedding model as the selector.
    pre_filtered: list[dict[str, Any]] | None = state.get("_filtered_tools")
    if pre_filtered:
        tool_dicts = []
        for t in pre_filtered:
            td = {k: v for k, v in t.items() if k != "_relevance_score"}
            tool_dicts.append(td)
    else:
        # Normal path: semantic search via selector
        if session_factory:
            async with session_factory() as session:
                tools = await selector.select(session, message=query)
        else:
            tools = await selector.select(None, message=query)
        tool_dicts: list[dict[str, Any]] = [t.model_dump(mode="json") for t in tools]

    # Merge direct matches into semantic results to ensure prerequisite
    # tools (e.g. get_geocoding for get_weather) are not missed
    semantic_names = {t.get("name") for t in tool_dicts if t.get("name")}
    merged = list(tool_dicts)
    for t in direct_matches:
        if t.get("name") not in semantic_names:
            merged.append(t)

    logger.info("tools.discovered", count=len(merged), query=query[:50], direct=len(direct_matches))
    return {"available_tools": merged}
