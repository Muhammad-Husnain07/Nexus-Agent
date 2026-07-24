"""dag_splitter node — dynamically split completed tasks into subtasks.

Examines completed DAG task results and decides whether to spawn subtasks
based on:
1. Rule-based list expansion: result contains a list of items → one subtask per item
2. LLM-based splitting: for complex results, asks LLM whether to split

New subtasks are injected into `dag_tasks` and processed in subsequent
`dag_expander` passes.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient
from nexus.utils.json_extractor import JsonExtractor

logger = structlog.get_logger("nexus.agent.nodes.dag_splitter")

_json_extractor = JsonExtractor()

_MERGEABLE_ARRAY_KEYS = {"results", "data", "items", "records", "users", "articles", "cities"}


def _extract_list_from_result(result_data: Any) -> list[Any] | None:
    """Extract a list of items from a tool result dict.

    Checks common array keys (results, data, items, etc.). Returns the
    first non-empty list found, or None.
    """
    if not isinstance(result_data, dict):
        return None
    for key in _MERGEABLE_ARRAY_KEYS:
        items = result_data.get(key)
        if isinstance(items, list) and len(items) > 1:
            return items
    return None


def _generate_subtasks(
    parent_task: dict[str, Any],
    items: list[Any],
    tool_name: str | None,
) -> list[dict[str, Any]]:
    """Generate one subtask per item from a list result.

    Each subtask inherits the parent's tool and passes the item as input.
    Subtasks depend_on the parent task.
    """
    parent_id: str = parent_task.get("id", "task_unknown")
    subtasks: list[dict[str, Any]] = []

    max_items = min(len(items), 5)
    for i, item in enumerate(items[:max_items]):
        item_id = f"{parent_id}_sub_{i}"
        item_inputs: dict[str, Any] = {}

        # Determine how to pass the item based on its type
        if isinstance(item, dict):
            item_inputs = dict(item)
        elif isinstance(item, str):
            item_inputs = {"value": item}
        else:
            item_inputs = {"item": item}

        subtask = {
            "id": item_id,
            "tool_name": tool_name,
            "inputs": item_inputs,
            "depends_on": [parent_id],
            "_parent": parent_id,
            "_item_index": i,
        }
        subtasks.append(subtask)

    return subtasks


async def dag_splitter(
    state: AgentState,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Examine completed DAG tasks and produce new subtasks if splitting is warranted.

    Strategy (in order):
    1. Rule-based list expansion: if a task's result contains a list of items
       with > 1 entry, create one subtask per item.
    2. LLM-based split decision: for complex results, optionally ask the LLM
       whether the result should be split into subtasks.

    Returns:
        Dict with ``new_tasks`` (list of new task dicts) and
        ``_routing_decision`` ("split" if new tasks created, else "continue").
    """
    tasks: list[dict[str, Any]] = state.get("dag_tasks", [])
    results: dict[str, Any] = state.get("dag_results", {})
    dag_gen: int = state.get("_dag_generation", 0)
    max_gen: int = get_settings().agent.adaptive_reflection.max_dag_generations

    if dag_gen >= max_gen:
        logger.info("dag_splitter.max_generations_reached", generation=dag_gen)
        return {"_routing_decision": "continue"}

    # Find tasks that completed in the latest batch but haven't been processed for splitting
    processed: list[str] = state.get("_pending_splits", [])
    new_tasks: list[dict[str, Any]] = []

    # Track working memory across all processed tasks
    try:
        from nexus.memory.working import WorkingMemory  # noqa: PLC0415
        _wm = WorkingMemory.from_dict(state.get("working_memory"))
    except Exception:
        _wm = None

    # Track which tools have been split — initialized ONCE before the task
    # loop so it accumulates across ALL tasks in this batch, not per-task
    # (state.get() always returns [] since the return dict isn't committed yet).
    _split_tools: list[str] = list(state.get("_split_tools", []))

    for task in tasks:
        task_id: str = task["id"]
        if task_id in processed:
            continue
        if task_id not in results:
            continue

        result_data = results.get(task_id)
        if result_data is None:
            continue

        # Strategy 1: Rule-based list expansion
        items = _extract_list_from_result(result_data)
        if items is not None:
            parent_tool: str | None = task.get("tool_name")
            if not parent_tool:
                approaches = task.get("approaches", [])
                if approaches:
                    parent_tool = approaches[0].get("tool_name")

            # Recursion guard: if this tool was already split in this DAG
            # generation (tracked via _split_tools), skip to prevent infinite
            # loops.  Splitting a tool's results into subtasks that call the
            # same tool again creates a recursive expansion e.g. geocoding
            # returns a list of cities → split each → geocode each city →
            # each returns another list → split again → ...
            if parent_tool and parent_tool in _split_tools:
                # Already split this tool in this DAG generation — skip to
                # prevent infinite loop (geocoding → split → geocode each → ...)
                logger.info("dag_splitter.skip_recursive",
                            parent=task_id, tool=parent_tool)
            else:
                # Register BEFORE creating subtasks so the guard is active
                # before any subtask completes and triggers another split.
                if parent_tool and parent_tool not in _split_tools:
                    _split_tools.append(parent_tool)
                subtasks = _generate_subtasks(task, items, parent_tool)
                if subtasks:
                    logger.info("dag_splitter.list_expansion",
                                parent=task_id, count=len(subtasks), tool=parent_tool)
                    new_tasks.extend(subtasks)

        # Strategy 2: LLM-based split decision for complex results
        if not items and llm is not None and model is not None and isinstance(result_data, dict) and len(result_data) > 1:
            try:
                from nexus.agent.prompts import prompt_manager  # noqa: PLC0415
                available_tools: list[dict[str, Any]] = state.get("available_tools", [])
                tool_names = [t.get("name", "") for t in available_tools if t.get("name")]
                max_sub = get_settings().agent.adaptive_reflection.max_concurrent_tasks

                split_prompt = prompt_manager.render_with_examples(
                    "dag_splitter",
                    version="1.0",
                    context={"response_type": "tool"},
                    max_examples=3,
                    max_mistakes=2,
                    max_subtasks=str(max_sub),
                )

                split_response = await llm.complete(
                    model=model,
                    messages=[
                        {"role": "system", "content": split_prompt},
                        {
                            "role": "user",
                            "content": (
                                f'Task "{task_id}" returned: {json.dumps(result_data, indent=2)[:800]}.\n'
                                f"Available tools: {tool_names}."
                            ),
                        },
                    ],
                    temperature=0,
                    response_format={"type": "json_object"},
                )

                split_content = _json_extractor.extract(split_response.content or "")
                split_parsed: dict[str, Any] = json.loads(split_content or "{}")
                if split_parsed.get("should_split") and split_parsed.get("subtasks"):
                    llm_subtasks: list[dict[str, Any]] = split_parsed["subtasks"]
                    for st in llm_subtasks:
                        if "id" not in st:
                            st["id"] = f"{task_id}_llm_{llm_subtasks.index(st)}"
                        if "depends_on" not in st:
                            st["depends_on"] = [task_id]
                    logger.info("dag_splitter.llm_split", parent=task_id, count=len(llm_subtasks))
                    new_tasks.extend(llm_subtasks)
            except Exception as exc:
                logger.warning("dag_splitter.llm_failed", error=str(exc), task_id=task_id)

        # Add working memory entry for tool result
        if _wm is not None:
            try:
                _wm.add(
                    key=f"tool:{task_id}",
                    content=str(result_data)[:100] if result_data else "(no data)",
                    source="tool_result",
                    importance=0.6,
                    turn_id=state.get("iteration_count", 0),
                )
            except Exception:
                pass

        processed.append(task_id)

    wm_final = _wm.to_dict() if _wm is not None else state.get("working_memory", {"entries": []})

    if not new_tasks:
        return {
            "_routing_decision": "continue",
            "_pending_splits": processed,
            "working_memory": wm_final,
            "_split_tools": list(_split_tools),
        }

    # Append new tasks to dag_tasks so dag_expander can process them
    existing_tasks: list[dict[str, Any]] = list(state.get("dag_tasks", []))
    dag_generation: int = state.get("_dag_generation", 0)

    logger.info("dag_splitter.injecting", new_count=len(new_tasks), existing=len(existing_tasks), generation=dag_generation)

    return {
        "dag_tasks": existing_tasks + new_tasks,
        "_pending_splits": processed,
        "_dag_generation": dag_generation + 1,
        "working_memory": wm_final,
        "_split_tools": list(_split_tools),
        "_routing_decision": "split",
    }
