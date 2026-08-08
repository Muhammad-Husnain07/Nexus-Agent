"""finalize node — compose the final answer from accumulated results."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import structlog

from nexus.agent.nodes.memory_helper_node import persist_after_response
from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.finalize")


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


async def _persist_memory_background(
    manager: Any,
    session_id: str,
    state: dict[str, Any],
) -> None:
    """Persist memories in background — does not block the response."""
    try:
        await manager.extract_and_store(session_id=session_id, agent_state=state)
    except Exception as exc:
        logger.warning("finalize.memory_persist_failed", error=str(exc))


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
    all_results: list[dict[str, Any]] = state.get("tool_results", [])
    errors: list[str] = state.get("errors", [])

    tool_executed = state.get("_tool_executed_in_turn", False)
    if tool_executed and all_results:
        # tool_results are per-turn (ephemeral) — no stale cross-turn
        # filtering needed (legacy ``dag_tasks`` filter removed — the field
        # was never populated).
        results = all_results
    else:
        results = []

    # If a final_response was already composed by a prior node (e.g.
    # respond_without_tool, or the background-execution handoff), use it
    # directly — skip recomposition. "background" carries the enqueued
    # task message; the worker owns the actual response.
    existing_final: str | None = state.get("final_response")
    _passthrough_types = ("greeting", "meta", "background", "cancellation", "clarification")
    if existing_final and (state.get("response_type") in _passthrough_types or not tool_executed):
        return {
            "messages": [],
            "final_response": existing_final,
            "working_memory": state.get("working_memory", {"entries": []}),
            "_routing_decision": "finalize",
        }
    elif errors and not results:
        final = "I encountered some issues:\n" + "\n".join(f"- {e}" for e in errors)
    elif results and tool_executed:
        _fin_settings = get_settings().agent
        _max_chars = _fin_settings.max_result_chars
        _max_items = _fin_settings.max_result_list_items

        def _truncate_data(d: Any) -> Any:
            if isinstance(d, str) and len(d) > _max_chars:
                return d[:_max_chars] + "..."
            if isinstance(d, dict):
                return {k: _truncate_data(v) for k, v in d.items()}
            if isinstance(d, list):
                return [_truncate_data(v) for v in d[:_max_items]] + (["..."] if len(d) > _max_items else [])
            return d

        tool_citations = json.dumps(
            [
                {
                    "name": r.get("tool_name"),
                    "status": r.get("status"),
                    "data": _truncate_data(r.get("data")),
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

        example_context = {
            "response_type": state.get("response_type", "tool"),
            "intent": (state.get("intent") or {}).get("intent", ""),
        }

        # Skip memory/working context for simple single-tool calls with no errors
        is_simple = len(results) <= 1 and not errors and not reflection_feedback
        if not is_simple:
            try:
                from nexus.memory.scout import MemoryScout  # noqa: PLC0415
                _scout = MemoryScout(llm=llm)
                _memory_ctx = await _scout.scout(
                    trigger="finalize",
                    context={"intent": example_context["intent"], "tool_results": results, "session_id": state.get("session_id")},
                )
            except Exception:
                _memory_ctx = ""
        else:
            _memory_ctx = ""

        # Inject working memory context
        if not is_simple:
            try:
                from nexus.memory.working import WorkingMemory  # noqa: PLC0415
                wm = WorkingMemory.from_dict(state.get("working_memory"))
                wm_ctx = wm.to_context(n=5)
            except Exception:
                wm_ctx = ""
        else:
            wm_ctx = ""

        system_prompt = prompt_manager.render_with_examples(
            "finalize",
            version="3.1",
            context=example_context,
            max_examples=2,
            max_mistakes=2,
            tool_citations=tool_citations,
            errors_summary=errors_summary,
        )
        if _memory_ctx:
            system_prompt = _memory_ctx + "\n\n" + system_prompt
        if wm_ctx:
            system_prompt = wm_ctx + "\n\n" + system_prompt
        if reflection_context:
            system_prompt = reflection_context + system_prompt

        _finalize_settings = get_settings().agent
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
            ],
            temperature=_finalize_settings.finalize_temperature,
            max_tokens=_finalize_settings.finalize_max_tokens,
        )
        if response.failed:
            logger.error("finalize.llm_failed", error=response.error)
            _err = f"LLM call failed: {response.error}"
            _apology = (
                "I'm sorry, I encountered an issue while composing the response. "
                "Please try again."
            )
            return {
                "final_response": _apology,
                "_routing_decision": "finalize",
                "response_type": "error",
                "errors": state.get("errors", []) + [_err],
            }
        final = response.content or "Task completed."
    else:
        final = "No results were produced."

    # Only milestone actual answers — skip for clarification/failure messages
    _milestone_min = get_settings().agent.milestone_min_length
    _is_clarification = not final or len(final) < _milestone_min
    final_msg = _openai_message("assistant", final, _milestone=not _is_clarification)

    # Persist to working memory + long-term memory
    working_memory_update = await persist_after_response(
        state, final, llm=llm, session_factory=session_factory
    )

    logger.info(
        "finalize.completed",
        result_length=len(final),
        errors=len(errors),
    )
    result_msgs = [final_msg]
    return {
        "messages": result_msgs,
        "final_response": final,
        "working_memory": working_memory_update,
        "_routing_decision": "finalize",
    }
