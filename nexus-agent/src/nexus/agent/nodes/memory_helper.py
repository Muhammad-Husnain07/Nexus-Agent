"""Shared memory persistence helper — used by terminal nodes (finalize, clarification).

Extracted from finalize.py so that clarification turns also persist to memory.
No hardcoded paths, no tool-specific logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger("nexus.agent.nodes.memory_helper")


def _truncate_for_memory(text: str, max_len: int = 200) -> str:
    return text[:max_len] if len(text) > max_len else text


async def persist_after_response(
    state: dict[str, Any],
    final_text: str,
    llm: Any = None,
    session_factory: Any = None,
) -> dict[str, Any]:
    """Persist the assistant's response to working memory and long-term memory.

    Args:
        state: The current AgentState dict.
        final_text: The assistant's final response text.
        llm: Optional LLM client (used for MemoryManager fallback path).
        session_factory: Optional DB session factory (used for MemoryStore fallback).

    Returns:
        Updated ``working_memory`` dict (or the original if persistence failed).
    """
    # Update working memory
    working_memory_update: dict[str, Any] | None = None
    try:
        from nexus.memory.working import WorkingMemory  # noqa: PLC0415

        wm = WorkingMemory.from_dict(state.get("working_memory"))
        wm.add(
            key="response",
            content=_truncate_for_memory(final_text),
            source="inference",
            importance=0.6,
            turn_id=state.get("iteration_count", 0),
        )
        working_memory_update = wm.to_dict()
    except Exception:
        working_memory_update = state.get("working_memory", {"entries": []})

    # Persist to long-term memory (Redis Stream if available, else in-process)
    if session_factory:
        _tried_stream = False
        try:
            import json as _json  # noqa: PLC0415
            from nexus.redis_client.client import get_redis_client  # noqa: PLC0415

            _r = get_redis_client()
            if _r is not None:
                _sid = state.get("session_id", "")
                _state_snapshot = dict(state)
                _state_snapshot.pop("messages", None)
                _state_snapshot.pop("dag_tasks", None)
                _state_snapshot.pop("available_tools", None)
                _state_snapshot.pop("tool_results", None)
                await _r.ping()
                await _r.xadd(
                    "memory_extraction_queue",
                    {
                        "session_id": _sid,
                        "agent_state": _json.dumps(_state_snapshot),
                    },
                    maxlen=1000,
                )
                _tried_stream = True
        except Exception:
            pass

        if not _tried_stream and llm is not None:
            try:
                from nexus.memory.manager import MemoryManager  # noqa: PLC0415
                from nexus.memory.store import MemoryStore  # noqa: PLC0415

                manager = MemoryManager(store=MemoryStore(), llm=llm)
                asyncio.ensure_future(
                    _persist_memory_background(
                        manager,
                        state.get("session_id", ""),
                        dict(state),
                    )
                )
            except Exception:
                pass

    return working_memory_update or state.get("working_memory", {"entries": []})


async def _persist_memory_background(
    manager: Any,
    session_id: str,
    state_snapshot: dict[str, Any],
) -> None:
    """Fire-and-forget background task to persist memory."""
    try:
        await manager.process_turn(
            session_id=session_id,
            messages=state_snapshot.get("messages", []),
            tool_results=state_snapshot.get("tool_results", []),
            structured_context=state_snapshot.get("_structured_context"),
        )
    except Exception as exc:
        logger.warning("memory_helper.persist_failed", error=str(exc))
