"""MemoryHelper — graph node for pgvector persistence + utility for working memory.

Contains:
1. ``memory_helper_node`` — @context_node graph node that persists session
   artifacts to long-term memory after the response.
2. ``persist_after_response`` — utility function used by finalize and
   clarification nodes to update working memory.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.node_wrapper import context_node
from nexus.agent.state import AgentState
from nexus.execution.context import ExecutionContext, StatePatch

logger = structlog.get_logger("nexus.agent.nodes.memory_helper")

# Background task tracking for graceful shutdown
_pending_bg_tasks: set[Any] = set()


# ============================================================================
# Utility: persist_after_response (used by finalize.py & clarification_node.py)
# ============================================================================


async def persist_after_response(
    state: AgentState,
    text: str,
    llm: Any = None,
    session_factory: Any = None,
) -> dict[str, Any]:
    """Extract working memory entries from the response text and persist them.

    Args:
        state: Current AgentState.
        text: The response text to extract memory from.
        llm: Optional LLM client for advanced extraction.
        session_factory: Optional DB session factory.

    Returns:
        Updated working_memory dict.
    """
    try:
        from nexus.memory.working import WorkingMemory

        wm = WorkingMemory.from_dict(state.get("working_memory"))
        wm.add(
            key="last_response",
            content=text[:1000],
            source="inference",
        )
        return wm.to_dict()
    except Exception as exc:
        logger.warning("memory_helper.persist_failed", error=str(exc))
        return state.get("working_memory", {"entries": []})


# ============================================================================
# Graph Node: memory_helper_node
# ============================================================================


@context_node
async def memory_helper_node(ctx: ExecutionContext) -> StatePatch:
    """Persist session artifacts to long-term memory."""
    snapshot = ctx.snapshot

    session_id = snapshot.get("session_id", "")
    messages = snapshot.get("messages", [])
    tool_results = snapshot.get("tool_results", [])
    aggregated = snapshot.get("_aggregated_results", {})

    memory_payload: dict[str, Any] = {
        "session_id": session_id,
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "tool_count": len(tool_results) if isinstance(tool_results, list) else 0,
        "aggregation_count": len(aggregated) if isinstance(aggregated, dict) else 0,
    }

    try:
        from nexus.memory.store import MemoryStore

        store = MemoryStore()
        last_msg = ""
        if isinstance(messages, list) and messages:
            for m in reversed(messages):
                if isinstance(m, dict) and m.get("role") == "user":
                    last_msg = str(m.get("content", ""))
                    break
        if last_msg:
            content = f"Query: {last_msg[:500]}\nTools: {len(tool_results)} results" if tool_results else f"Query: {last_msg[:500]}"
            try:
                await store.put(
                    session_id=session_id if session_id else None,
                    kind="episodic",
                    content=content,
                    metadata={
                        "query": last_msg[:200],
                        "tool_count": len(tool_results) if isinstance(tool_results, list) else 0,
                        "aggregation_count": len(aggregated) if isinstance(aggregated, dict) else 0,
                    },
                )
                logger.info(
                    "memory_helper.stored",
                    session_id=session_id,
                    artifacts=len(tool_results) if isinstance(tool_results, list) else 0,
                )
            except Exception as mem_exc:
                logger.warning("memory_helper.store_episodic_failed", error=str(mem_exc))
    except Exception as exc:
        logger.warning("memory_helper.store_failed", error=str(exc))

    return StatePatch(
        version=ctx.version + 1,
        updates={"_memory_persisted": memory_payload},
    )
