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

    REINFORCEMENT GATE (Step 6): a failed/degenerate synthesis must never
    enter working memory — prior failed responses ("I don't have temperature
    information...") were scouted back into planning and reinforced failure.
    Persistence is skipped when the response is an error, synthesis degraded
    (``_synthesis_failed``), or the text is too short to carry content.
    Typed signals only — no hardcoding.

    Args:
        state: Current AgentState.
        text: The response text to extract memory from.
        llm: Optional LLM client for advanced extraction.
        session_factory: Optional DB session factory.

    Returns:
        Updated working_memory dict.
    """
    response_type = str(state.get("response_type") or "")
    synthesis_failed = bool(state.get("_synthesis_failed"))
    degenerate = len((text or "").strip()) < 40
    if response_type == "error" or synthesis_failed or degenerate:
        logger.info(
            "memory_helper.response_not_persisted",
            reason="error" if response_type == "error"
            else "synthesis_failed" if synthesis_failed else "degenerate",
        )
        return state.get("working_memory", {"entries": []})
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
async def memory_helper_node(ctx: ExecutionContext, llm: Any, model: str) -> StatePatch:
    """Persist session artifacts to long-term memory via MemoryManager.

    SELECTIVE persistence: turns that executed no tools and produced no
    artifacts (greetings, pure conversation, clarification asks) are skipped —
    LLM-driven memory extraction costs 2 LLM calls per turn and adds no value
    when there is nothing factual to remember. Only turns with tool output or
    artifacts write to long-term memory.
    """
    snapshot = ctx.snapshot
    session_id = snapshot.get("session_id", "")

    # C8 — memory gating: skip LLM-based extraction when nothing executable
    # happened this turn (no tools, no artifacts, no execution errors).
    tool_results = snapshot.get("tool_results") or []
    has_tool_work = bool(tool_results) or bool(snapshot.get("errors"))
    if not has_tool_work:
        logger.info(
            "memory_helper.skipped_no_tool_work",
            session_id=str(session_id),
        )
        return StatePatch(
            version=ctx.version + 1,
            updates={"_memory_persisted": {"session_id": session_id, "stored_memory_ids": [], "skipped": "no_tool_work"}},
        )

    # Build agent_state dict for MemoryManager
    agent_state = dict(snapshot)

    # Inject ArtifactGraph facts into the state so MemoryManager can see them
    from nexus.artifacts.graph import get_artifact_graph
    import json

    artifact_graph = get_artifact_graph(str(session_id))
    all_artifacts = artifact_graph.all()
    artifact_facts: list[str] = []
    artifact_memories: list[str] = []
    for art in all_artifacts:
        data_str = json.dumps(art.data, default=str)[:500]
        artifact_facts.append(f"{art.type} ({art.tool_name}): {data_str}")
        # ARTIFACT MEMORY (Phase 3, additive): structured outputs persisted
        # keyed by (artifact_type, canonical content_hash, schema_version) —
        # dedup-safe across repeated cache hits, zero LLM calls.
        from nexus.memory.artifact_memory import store_artifact_memory

        stored = await store_artifact_memory(
            session_id=str(session_id) if session_id else None,
            artifact_type=art.type,
            tool_name=art.tool_name,
            schema_version=art.schema_version,
            content_hash=art.content_hash,
            payload=getattr(art, "data", None) or {},
        )
        if stored:
            artifact_memories.append(art.type)

    if artifact_facts:
        agent_state["_artifact_facts"] = "\n".join(artifact_facts)
    if artifact_memories:
        logger.info(
            "memory_helper.artifact_memory_stored",
            session_id=str(session_id),
            kinds=sorted(set(artifact_memories)),
        )

    stored_ids: list[str] = []
    try:
        from nexus.memory.manager import MemoryManager

        manager = MemoryManager(llm=llm)
        stored_ids = await manager.extract_and_store(
            session_id=session_id,
            agent_run_id=None,
            agent_state=agent_state,
        )
        logger.info(
            "memory_helper.stored_via_manager",
            session_id=session_id,
            memory_count=len(stored_ids),
        )
    except Exception as exc:
        logger.warning("memory_helper.manager_failed", error=str(exc))

    memory_payload: dict[str, Any] = {
        "session_id": session_id,
        "stored_memory_ids": stored_ids,
    }

    return StatePatch(
        version=ctx.version + 1,
        updates={"_memory_persisted": memory_payload},
    )
