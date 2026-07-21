"""dag_expander node — generate and advance a DAG of parallel tool tasks.

Produces a plan DAG via LLM, then a conditional routing function fans out
ready (no-dependency) tasks in parallel using LangGraph's ``Send()`` API.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from langgraph.types import Send

from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.dag_expander")


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

    # First call — generate plan via LLM
    tools: list[dict[str, Any]] = state.get("available_tools", [])
    tool_descriptions = json.dumps(
        [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "purpose": t.get("purpose", ""),
                "input_schema": t.get("input_schema", {}),
                "examples": (t.get("examples") or [])[:2],
            }
            for t in tools
        ],
        indent=2,
    )
    intent: dict[str, Any] = state.get("intent") or {}
    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    settings = get_settings().agent

    system_prompt = prompt_manager.render(
        "plan_parallel",
        version="1.0",
        tool_descriptions=tool_descriptions,
        max_tasks=str(settings.max_plan_steps),
    )

    user_context = json.dumps(
        {
            "intent": intent.get("intent", ""),
            "parameters": intent.get("parameters", {}),
            "gathered_requirements": gathered,
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
        response_format={"type": "json_object"},
    )

    content = (response.content or "").strip()
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        content = json_match.group(0)

    try:
        parsed: dict[str, Any] = json.loads(content)
        tasks: list[dict[str, Any]] = parsed.get("tasks", [])
        if not tasks:
            raise ValueError("No tasks in plan")
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("dag_expander.parse_failed", error=str(exc), content=content[:200])
        tasks = _fallback_plan(intent, gathered)

    logger.info("dag_expander.plan_created", task_count=len(tasks))
    return {
        "dag_tasks": tasks,
        "dag_results": {},
        "dag_phase": "expanding",
        "plan": [
            {
                "id": t["id"],
                "description": f"{t['tool_name']}({json.dumps(t.get('inputs', {}))})",
                "tool_name": t.get("tool_name"),
                "inputs": t.get("inputs", {}),
                "status": "pending",
                "depends_on": t.get("depends_on", []),
                "expected_outcome": f"Execute {t['tool_name']}",
                "is_destructive": False,
            }
            for t in tasks
        ],
    }


def route_dag(state: AgentState) -> list[Send] | str:
    """Conditional edge: fan out ready tasks or finish.

    Reads ``dag_tasks`` and ``dag_results`` from state, finds tasks whose
    dependencies are satisfied, and fans each one out via ``Send()`` to
    ``tool_executor``.  When no tasks remain, routes to ``finalize``.
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
        # If no tasks can proceed and some completed tasks failed, route to ask
        failed = any(
            results.get(t["id"]) is None
            for t in tasks
            if t["id"] in results
        )
        if failed and remaining:
            logger.info("dag_expander.ask_clarification", failed_count=sum(1 for t in tasks if t["id"] in results and results[t["id"]] is None))
            return "ask"
        logger.info("dag_expander.all_done", total=len(tasks))
        return "finalize"

    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    logger.info("dag_expander.fan_out", ready_ids=[t["id"] for t in ready], dag_keys=list(results.keys()), remaining=len(remaining))
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
