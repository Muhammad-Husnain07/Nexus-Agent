"""finalize node — compose the final answer from accumulated results."""

from __future__ import annotations

import asyncio
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


async def _persist_memory_background(
    manager: MemoryManager,
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

    # Use tool results from current turn only. If no tool was executed
    # this turn, discard stale results from previous turns.
    tool_executed = state.get("_tool_executed_in_turn", False)
    if tool_executed and all_results:
        # Keep only results whose tool_name matches current dag_tasks
        current_task_names = {
            t.get("tool_name") for t in (state.get("dag_tasks") or [])
            if t.get("tool_name")
        }
        if current_task_names:
            results = [r for r in all_results if r.get("tool_name") in current_task_names]
        else:
            results = all_results
    else:
        results = []

    # If a final_response was already composed by a prior node (e.g.
    # respond_without_tool), use it directly — skip recomposition.
    existing_final: str | None = state.get("final_response")
    if existing_final and (state.get("response_type") in ("greeting", "meta") or not tool_executed):
        final = existing_final
    elif errors and not results:
        final = "I encountered some issues:\n" + "\n".join(f"- {e}" for e in errors)
    elif results and tool_executed:
        def _truncate_data(d: Any, max_chars: int = 2000) -> Any:
            if isinstance(d, str) and len(d) > max_chars:
                return d[:max_chars] + "..."
            if isinstance(d, dict):
                return {k: _truncate_data(v, max_chars) for k, v in d.items()}
            if isinstance(d, list):
                return [_truncate_data(v, max_chars) for v in d[:5]] + (["..."] if len(d) > 5 else [])
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
                    context={"intent": example_context["intent"], "tool_results": results},
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
            version="3.0",
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

        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
            ],
            temperature=0.7,
            max_tokens=1024,
            stop=["User:", "user:", "###"],
        )
        final = response.content or "Task completed."
    else:
        final = "No results were produced."

    final_msg = _openai_message("assistant", final, _milestone=True)

    # Add working memory entry for the final response
    try:
        from nexus.memory.working import WorkingMemory  # noqa: PLC0415
        wm = WorkingMemory.from_dict(state.get("working_memory"))
        wm.add(
            key="final_response",
            content=final[:200],
            source="inference",
            importance=0.6,
            turn_id=state.get("iteration_count", 0),
        )
        working_memory_update = wm.to_dict()
    except Exception:
        working_memory_update = state.get("working_memory", {"entries": []})

    # Persist to long-term memory (Redis Stream if available, else in-process)
    if session_factory and state.get("response_type") == "tool":
        _tried_stream = False
        try:
            import json as _json
            from nexus.redis_client.client import get_redis_client  # noqa: PLC0415
            _r = get_redis_client()
            if _r is not None:
                _sid = state.get("session_id", "")
                _state_snapshot = dict(state)
                _state_snapshot.pop("messages", None)
                _state_snapshot.pop("dag_tasks", None)
                _state_snapshot.pop("dag_results", None)
                _state_snapshot.pop("available_tools", None)
                _state_snapshot.pop("tool_results", None)
                # Test connection with ping before xadd
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

        if not _tried_stream:
            try:
                manager = MemoryManager(store=MemoryStore(), llm=llm)
                asyncio.ensure_future(_persist_memory_background(manager, state.get("session_id", ""), dict(state)))
            except Exception:
                pass

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
