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

    # If a final_response was already composed by a prior node (e.g.
    # respond_without_tool), use it directly — skip recomposition.
    existing_final: str | None = state.get("final_response")
    if existing_final:
        final = existing_final
    elif errors and not results:
        final = "I encountered some issues:\n" + "\n".join(f"- {e}" for e in errors)
    elif results:
        tool_citations = json.dumps(
            [
                {
                    "name": r.get("tool_name"),
                    "status": r.get("status"),
                    "data": r.get("data"),
                    "error": r.get("error"),
                }
                for r in results
            ],
            indent=2,
        )
        # Collect errors from tool results that failed
        tool_errors = [
            r.get("error", "") or f"Tool '{r.get('tool_name')}' returned no data"
            for r in results
            if r.get("error") or r.get("data") is None
        ]
        errors_summary = "\n".join(errors + tool_errors) if (errors or tool_errors) else "None"

        reflection_feedback = state.get("reflection_feedback", "") or ""
        reflection_context = (
            f"<improvement_feedback>\n{reflection_feedback}\n</improvement_feedback>\n\n"
            if reflection_feedback
            else ""
        )

        user_prompt = prompt_manager.render(
            "finalize",
            version="2.0",
            tool_citations=tool_citations,
            errors_summary=errors_summary,
        )
        if reflection_context:
            user_prompt = reflection_context + user_prompt

        response = await llm.complete(
            model=model,
            messages=[_openai_message("user", user_prompt)],
            temperature=0.7,
        )
        final = response.content or "Task completed."
    else:
        final = "No results were produced."

    final_msg = _openai_message("assistant", final)

    # Persist to long-term memory via MemoryManager (skip for non-tool interactions)
    mem_error: str | None = None
    if session_factory and state.get("response_type") == "tool":
        try:
            manager = MemoryManager(
                store=MemoryStore(),
                llm=llm,
            )
            await manager.extract_and_store(
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
        "messages": [final_msg],
        "_routing_decision": "finalize",
    }
