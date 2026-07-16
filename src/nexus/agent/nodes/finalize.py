"""finalize node — compose the final answer from accumulated results."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import structlog

from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState
from nexus.llm.client import LLMClient
from nexus.memory.manager import MemoryManager
from nexus.memory.store import MemoryStore

logger = structlog.get_logger("nexus.agent.nodes.finalize")


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


async def finalize(
    state: AgentState,
    llm: LLMClient,
    model: str,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Compose the final answer from accumulated tool results and errors.

    Uses the ``finalize`` prompt template (version 2.0).  Persists a
    summary to the ``Memory`` (episodic) table when ``session_factory``
    is provided.

    Returns:
        Dict with ``final_response`` and updated ``messages``.
    """
    results: list[dict[str, Any]] = state.get("tool_results", [])
    errors: list[str] = state.get("errors", [])

    if errors and not results:
        final = "I encountered some issues:\n" + "\n".join(f"- {e}" for e in errors)
    elif results:
        tool_citations = json.dumps(
            [
                {
                    "name": r.get("tool_name"),
                    "status": r.get("status"),
                    "data": r.get("data"),
                }
                for r in results
                if r.get("status") == "success"
            ],
            indent=2,
        )
        errors_summary = "\n".join(errors) if errors else "None"

        user_prompt = prompt_manager.render(
            "finalize",
            version="2.0",
            tool_citations=tool_citations,
            errors_summary=errors_summary,
        )

        response = await llm.complete(
            model=model,
            messages=[_openai_message("user", user_prompt)],
            temperature=0.7,
        )
        final = response.content or "Task completed."
    else:
        final = "No results were produced."

    messages: list[dict[str, Any]] = list(state.get("messages", []))
    messages.append(_openai_message("assistant", final))

    # Persist to long-term memory via MemoryManager
    mem_error: str | None = None
    if session_factory:
        try:
            manager = MemoryManager(
                store=MemoryStore(),
                llm=llm,
            )
            await manager.extract_and_store(
                tenant_id=state.get("tenant_id", ""),
                user_id=state.get("user_id", ""),
                session_id=state.get("session_id", ""),
                agent_state=dict(state),
            )
        except Exception as exc:
            mem_error = str(exc)
            logger.warning("finalize.memory_persist_failed", error=mem_error)

    logger.info(
        "finalize.completed",
        result_length=len(final),
        errors=len(errors),
        memory_error=mem_error is not None,
    )
    return {
        "final_response": final,
        "messages": messages,
        "_routing_decision": "finalize",
    }
