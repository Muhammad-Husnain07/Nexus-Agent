"""dag_expander node — generate and advance a DAG of parallel tool tasks.

Produces a plan DAG via LLM, then a conditional routing function fans out
ready (no-dependency) tasks in parallel using LangGraph's ``Send()`` API.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import structlog
from langgraph.types import Send

from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.observability.tracing import get_tracer
from nexus.utils.json_extractor import JsonExtractor

logger = structlog.get_logger("nexus.agent.nodes.dag_expander")

_json_extractor = JsonExtractor()


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


async def dag_expander(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Generate a DAG plan or advance to next batch of tasks.

    On first call (dag_tasks is empty), calls LLM to produce a DAG.
    On subsequent calls, state already has dag_tasks populated — no LLM call needed.

    Returns:
        State updates and optionally ``Send`` objects via the conditional edge.
    """
    # If plan already exists, just acknowledge — routing happens in conditional edge
    if state.get("dag_tasks"):
        logger.info("dag_expander.advance", pending=sum(1 for t in state["dag_tasks"] if t["id"] not in (state.get("dag_results") or {})))
        return {"dag_phase": "expanding"}

    # First call — generate plan
    tools: list[dict[str, Any]] = state.get("available_tools", [])
    intent: dict[str, Any] = state.get("intent") or {}
    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    settings = get_settings().agent

    # Fast path: single tool — skip LLM, generate direct plan
    if len(tools) == 1:
        tool = tools[0]
        tasks = [{
            "id": "task_1",
            "tool_name": tool["name"],
            "description": tool.get("description", ""),
            "inputs": {},
            "depends_on": [],
        }]
        logger.info("dag_expander.fast_path", tool=tool["name"])
    else:
        # Prune tool schemas — keep only required fields + types, drop examples
        def _prune_schema(schema: dict[str, Any]) -> str:
            """Strip non-required fields from input_schema for a compact summary."""
            if not schema or not isinstance(schema, dict):
                return "{}"
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            # Keep only: field name, type, and whether it's required
            compact = {}
            for name, prop in props.items():
                if isinstance(prop, dict):
                    compact[name] = {"type": prop.get("type", "any"), "required": name in required}
            return json.dumps(compact)

        tool_descriptions = json.dumps(
            [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "purpose": t.get("purpose", ""),
                    "input_schema": _prune_schema(t.get("input_schema", {})),
                }
                for t in tools
            ],
            indent=2,
        )

        example_context = {
            "response_type": "tool",
            "intent": intent.get("intent", ""),
        }

        system_prompt = prompt_manager.render_with_examples(
            "plan_parallel",
            version="1.0",
            context=example_context,
            max_examples=3,
            max_mistakes=3,
            tool_descriptions=tool_descriptions,
            max_tasks=str(settings.max_plan_steps),
        )

        confidence: float = state.get("confidence", 1.0)
        multi_tool_available = len(tools) > 1
        suggest_speculative = confidence < 0.9 and multi_tool_available

        # Check Redis plan cache — same intent + same tool list → reuse plan
        intent_key = _plan_cache_key(intent.get("intent", ""), tools)
        cached_tasks = await _get_cached_plan(intent_key)
        if cached_tasks:
            tasks = cached_tasks
            logger.info("dag_expander.plan_cache_hit", intent=intent.get("intent","")[:40])
        else:
            user_context = json.dumps(
                {
                    "intent": intent.get("intent", ""),
                    "parameters": intent.get("parameters", {}),
                    "gathered_requirements": gathered,
                    "speculative_execution_available": suggest_speculative,
                    "speculative_hint": (
                        "You may use the 'approaches' field (list of {tool_name, inputs}) "
                        "for tasks where multiple tools or parameter formats could work. "
                        "The system races them and uses the first successful result."
                        if suggest_speculative
                        else None
                    ),
                },
                indent=2,
            )

            response = await llm.complete(
            model=model,
            messages=[
                _openai_message("system", system_prompt),
                _openai_message("user", user_context),
            ],
            temperature=0,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )

        content = _json_extractor.extract(response.content or "")

        try:
            parsed: dict[str, Any] = json.loads(content)
            tasks: list[dict[str, Any]] = parsed.get("tasks", [])
            if not tasks:
                raise ValueError("No tasks in plan")
            await _set_cached_plan(intent_key, tasks)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("dag_expander.parse_failed", error=str(exc), content=content[:200])
            tasks = _fallback_plan(intent, gathered)

    _span_dag = get_tracer().start_span("agent.dag_expand")
    _span_dag.set_attribute("dag.task_count", len(tasks))
    _span_dag.end()

    logger.info("dag_expander.plan_created", task_count=len(tasks))
    return {
        "dag_tasks": tasks,
        "dag_results": {},
        "dag_phase": "expanding",
        "plan": [
            {
                "id": t["id"],
                "description": t.get("description") or t.get("tool_name") or (t.get("approaches") or [{}])[0].get("tool_name") or "execute",
                "tool_name": t.get("tool_name") or (t.get("approaches") or [{}])[0].get("tool_name"),
                "inputs": t.get("inputs", {}),
                "status": "pending",
                "depends_on": t.get("depends_on", []),
                "expected_outcome": f"Execute {t.get('tool_name') or 'direct'}",
                "is_destructive": False,
            }
            for t in tasks
        ],
    }


# ── Plan cache helpers (Redis, TTL 10min) ──────────────────────────────
_PLAN_CACHE_TTL: int = 600


def _plan_cache_key(intent: str, tools: list[dict[str, Any]]) -> str:
    """Build a deterministic cache key from intent + tool names."""
    tool_names = sorted(t.get("name", "") for t in tools if t.get("name"))
    raw = f"{intent}|{'|'.join(tool_names)}"
    return f"plan_cache:{hashlib.md5(raw.encode()).hexdigest()}"


async def _get_cached_plan(key: str) -> list[dict[str, Any]] | None:
    """Get cached plan from Redis. Returns None if miss."""
    try:
        from nexus.redis_client.client import get_redis_client
        redis = get_redis_client()
        if redis is None:
            return None
        data = await redis.get(key)
        if data:
            import json
            return json.loads(data)
    except Exception:
        pass
    return None


async def _set_cached_plan(key: str, tasks: list[dict[str, Any]]) -> None:
    """Cache a plan in Redis with TTL."""
    try:
        from nexus.redis_client.client import get_redis_client
        redis = get_redis_client()
        if redis is None:
            return
        import json
        await redis.setex(key, _PLAN_CACHE_TTL, json.dumps(tasks))
    except Exception:
        pass


def route_dag(state: AgentState) -> list[Send] | str:
    """Conditional edge: fan out ready tasks or finish.

    Reads ``dag_tasks`` and ``dag_results`` from state, finds tasks whose
    dependencies are satisfied, and fans each one out via ``Send()`` to
    ``tool_executor``.  Respects ``_max_concurrent_tasks`` bound.

    When no tasks remain, routes to ``finalize``.
    """
    tasks: list[dict[str, Any]] = state.get("dag_tasks", [])
    results: dict[str, Any] = state.get("dag_results", {})

    remaining = [t for t in tasks if t["id"] not in results]
    if not remaining:
        logger.info("dag_expander.all_done", total=len(tasks))
        return "finalize"

    ready = [t for t in remaining if all(
        d in results and results[d] is not None
        for d in t.get("depends_on", [])
    )]
    if not ready:
        # Check if remaining tasks are blocked by failed dependencies
        failed_ids = {
            t["id"] for t in tasks
            if t["id"] in results and results[t["id"]] is None
        }
        blocked_by_failure = remaining and all(
            any(d in failed_ids for d in t.get("depends_on", []))
            for t in remaining
            if t.get("depends_on")
        )
        if failed_ids and remaining:
            if blocked_by_failure:
                logger.info("dag_expander.finalize_blocked", failed_ids=list(failed_ids), remaining=[t["id"] for t in remaining])
                return "finalize"
            logger.info("dag_expander.ask_clarification", failed_count=len(failed_ids))
            return "ask"
        logger.info("dag_expander.all_done", total=len(tasks))
        return "finalize"

    # Bounded parallelism: respect _max_concurrent_tasks
    max_concurrent: int = state.get("_max_concurrent_tasks") or get_settings().agent.adaptive_reflection.max_concurrent_tasks
    in_flight = sum(
        1 for t in tasks
        if t["id"] in results and results[t["id"]] is None
    )
    available_slots = max(1, max_concurrent - in_flight)
    bounded_ready = ready[:available_slots]

    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    logger.info("dag_expander.fan_out", ready_ids=[t["id"] for t in bounded_ready], max_concurrent=max_concurrent, in_flight=in_flight, remaining=len(remaining))
    return [
        Send(
            "tool_executor",
            {
                "task": t,
                "available_tools": state.get("available_tools", []),
                "dag_results": dict(results),
                "gathered_requirements": gathered,
            },
        )
        for t in ready
    ]


def _fallback_plan(intent: dict[str, Any], gathered: dict[str, Any]) -> list[dict[str, Any]]:
    """Fallback single-task plan when LLM parsing fails."""
    goal = intent.get("intent", "") or "Execute user request"
    params = dict(intent.get("parameters", {}))
    params.update(gathered)
    return [
        {
            "id": "task_1",
            "tool_name": None,
            "inputs": params,
            "depends_on": [],
        }
    ]
