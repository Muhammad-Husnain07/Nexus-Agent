"""tool_executor node — execute a single DAG task with speculative support.

Receives a task slice via ``Send()`` with the task definition and
available tools.  If the task has multiple ``approaches`` (different tools
or parameter variations), they are raced in parallel via speculative
execution — the first successful result wins, and remaining approaches
are cancelled.  Single-approach tasks execute directly (no change).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

import structlog

from nexus.config.settings import get_settings
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.agent.nodes.tool_executor")


async def _auto_chain_tool(
    tool_name: str,
    raw_inputs: dict[str, Any],
    available_tools: list[dict[str, Any]],
    dag_results: dict[str, Any],
    gathered: dict[str, Any],
    task_id: str,
    session: Any = None,
) -> dict[str, Any]:
    """Try to find and execute a prerequisite tool when required inputs are missing.

    For example: if get_weather needs latitude/longitude but only a city name
    is provided, automatically call get_geocoding first and merge its output.
    """
    input_schema = {}
    for t in available_tools:
        if t.get("name") == tool_name:
            input_schema = t.get("input_schema", {})
            break

    schemas_props = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
    required = input_schema.get("required", []) if isinstance(input_schema, dict) else []
    missing = [f for f in required if f not in raw_inputs and f not in dag_results]

    if not missing:
        return None

    # Try chaining: execute any tool that can accept available inputs and return missing fields
    for chained_name in [t["name"] for t in available_tools if t.get("name") != tool_name]:
        chained_schema = next((t.get("output_schema", {}) for t in available_tools if t.get("name") == chained_name), {})
        chained_keys = set(chained_schema.get("properties", {}).keys()) if isinstance(chained_schema, dict) else set()
        # If output_schema is empty, try chaining anyway — the API may return matching fields
        if not chained_keys:
            chained_keys = set(missing)
        missing_keys = set(missing)
        if chained_keys & missing_keys:
            chained_inputs = {k: v for k, v in raw_inputs.items() if k not in schemas_props}
            if not chained_inputs:
                chained_inputs = raw_inputs
            chained = await _execute_single_approach(
                {"tool_name": chained_name, "inputs": chained_inputs},
                available_tools, dag_results, gathered, f"{task_id}_prereq",
                session=session,
            )
            if chained.get("status") == "success" and isinstance(chained.get("data"), dict):
                merged = {**raw_inputs, **chained["data"]}
                return merged
    return None


async def _execute_single_approach(
    approach: dict[str, Any],
    available_tools: list[dict[str, Any]],
    dag_results: dict[str, Any],
    gathered: dict[str, Any],
    task_id: str,
    session: Any = None,
) -> dict[str, Any]:
    """Execute a single tool approach and return the result dict."""
    tool_name: str | None = approach.get("tool_name")
    if not tool_name:
        return {"tool_name": None, "status": "success", "data": None, "error": None, "task_id": task_id}

    raw_inputs: dict[str, Any] = approach.get("inputs", {})
    resolved_inputs = _resolve_placeholders(raw_inputs, dag_results, gathered)

    tool_dict = _find_tool(tool_name, available_tools)
    if not tool_dict:
        return {"tool_name": tool_name, "status": "error", "data": None, "error": f"Tool '{tool_name}' not found", "task_id": task_id}

    # Auto-chain prerequisite tools for missing required inputs
    chained = await _auto_chain_tool(tool_name, resolved_inputs, available_tools, dag_results, gathered, task_id, session)
    if chained is not None:
        resolved_inputs = chained

    try:
        tool_read = _tool_to_read(tool_dict)
        executor = ToolExecutor()
        context = ExecutionContext(session_id="", agent_run_id="")

        result: ToolResult = await executor.execute(
            tool_read, resolved_inputs, context,
            skip_approval=not tool_read.requires_approval, session=session,
        )

        result_data = result.data if result.status == "success" else None
        error = result.error if result.status != "success" else None

        _META_KEYS = {"generationtime_ms", "utc_offset_seconds", "timezone", "timezone_abbreviation", "elevation"}
        if result_data and isinstance(result_data, dict):
            has_data_key = False
            for _key in ("results", "data", "items"):
                _items = result_data.get(_key)
                if isinstance(_items, list):
                    if len(_items) > 0:
                        has_data_key = True
                    else:
                        result_data = None
                        error = error or f"API returned no results for '{_key}'"
                        break
            if result_data is not None:
                non_meta = [k for k in result_data if k not in _META_KEYS]
                if not has_data_key and not non_meta:
                    result_data = None
                    error = error or "API returned no data"

        # Mark null/empty results as errors so the agent can respond
        # informatively instead of silently dropping the tool output.
        final_status = result.status
        if result_data is None and final_status == "success" and tool_name:
            error = error or f"Tool '{tool_name}' returned empty data"
            final_status = "error"

        return {
            "tool_name": tool_name,
            "status": final_status,
            "data": result_data,
            "error": error,
            "task_id": task_id,
            "duration_ms": result.duration_ms,
        }
    except Exception as exc:
        return {"tool_name": tool_name, "status": "error", "data": None, "error": str(exc), "task_id": task_id}


async def _speculative_execute(
    approaches: list[dict[str, Any]],
    available_tools: list[dict[str, Any]],
    dag_results: dict[str, Any],
    gathered: dict[str, Any],
    task_id: str,
    max_approaches: int = 3,
    timeout: float = 15.0,
    session: Any = None,
) -> dict[str, Any]:
    """Race multiple tool approaches via speculative execution.

    Launches all approaches in parallel, returns the first successful result,
    and cancels remaining approaches.  If none succeed, returns the first error.
    """
    if len(approaches) <= 1:
        return await _execute_single_approach(
            approaches[0] if approaches else {"tool_name": None, "inputs": {}},
            available_tools, dag_results, gathered, task_id,
            session=session,
        )

    bounded = approaches[:max_approaches]

    async def _run_guarded(approach: dict[str, Any]) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(
                _execute_single_approach(approach, available_tools, dag_results, gathered, task_id, session=session),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return {"tool_name": approach.get("tool_name"), "status": "error",
                    "data": None, "error": "Speculative branch timed out", "task_id": task_id}

    tasks = {i: asyncio.create_task(_run_guarded(a)) for i, a in enumerate(bounded)}

    # Wait for any to complete
    done, pending = await asyncio.wait(
        list(tasks.values()),
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Check completed for a success
    for t in done:
        try:
            result = t.result()
            if result.get("status") == "success" and result.get("data") is not None:
                for p in pending:
                    p.cancel()
                await asyncio.wait(pending, timeout=2.0)
                logger.info("speculative.success", task_id=task_id, tool=result.get("tool_name"))
                return result
        except Exception:
            continue

    # No success yet — wait for all to finish
    if pending:
        await asyncio.wait(pending, timeout=timeout - 1.0)

    # Return first successful result if any, otherwise first error
    results: list[dict[str, Any]] = []
    for t in tasks.values():
        try:
            r = t.result()
            if r.get("status") == "success":
                return r  # another succeeded while we were waiting
            results.append(r)
        except (asyncio.CancelledError, Exception):
            continue

    return results[0] if results else {"tool_name": None, "status": "error", "data": None, "error": "All speculative approaches failed", "task_id": task_id}


def _find_tool(
    tool_name: str | None,
    available_tools: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a tool definition by name in the available tools list."""
    if not tool_name:
        return None
    for t in available_tools:
        if t.get("name") == tool_name:
            return t
    return None


def _resolve_placeholders(
    inputs: dict[str, Any],
    dag_results: dict[str, Any],
    gathered_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve ``${{task_id.result.field}}``, ``${task_id.result.field}``,
    and ``${gathered_requirements.field}`` placeholders.

    Recursively walks the input dict and replaces placeholder strings
    with the actual values from completed task results or gathered info.
    """
    gathered = gathered_requirements or {}

    def _resolve(val: Any) -> Any:
        if isinstance(val, str):
            # Resolve ${gathered_requirements.field} — use actual value
            gr_match = re.match(r"^\$\{gathered_requirements\.(.+?)\}$", val)
            if gr_match:
                key = gr_match.group(1)
                # Support list index syntax: locations[0] → locations, 0
                _li = re.match(r"^(.+?)\[(\d+)\]$", key)
                if _li:
                    _items = gathered.get(_li.group(1), [])
                    if isinstance(_items, list) and 0 <= int(_li.group(2)) < len(_items):
                        return _items[int(_li.group(2))]
                return gathered.get(key, val)
            # Resolve ${task_id.result.field} or ${{task_id.result.field}}
            match = re.match(r"^\$?\{\{?(.+?)\.result(?:\.(.+?))?\}?\}$", val)
            if match:
                task_id = match.group(1)
                field_path = match.group(2)
                result = dag_results.get(task_id, {})
                # Handle None/empty results — return placeholder unresolved
                if result is None:
                    return val
                # Auto-unwrap single-item result arrays from any API
                if isinstance(result, dict):
                    for _key in ("results", "data", "items"):
                        _items = result.get(_key)
                        if isinstance(_items, list) and len(_items) == 1:
                            result = {**result, **_items[0]}
                            break
                    # If result is an empty dict after unwrap, treat as None
                    if not result:
                        return val
                # Deep recursive search for field in nested structures
                if field_path and isinstance(result, dict):
                    _MISSING = object()
                    def _deep_search(d: Any, key: str) -> Any:
                        if isinstance(d, dict):
                            if key in d:
                                return d[key]
                            for v in d.values():
                                found = _deep_search(v, key)
                                if found is not _MISSING:
                                    return found
                        elif isinstance(d, list):
                            for item in d:
                                found = _deep_search(item, key)
                                if found is not _MISSING:
                                    return found
                        return _MISSING
                    found = _deep_search(result, field_path)
                    if found is not _MISSING:
                        return found
                if field_path:
                    parts = field_path.split(".")
                    for part in parts:
                        if isinstance(result, dict):
                            result = result.get(part, val)
                        else:
                            return val
                return result
            return val
        if isinstance(val, dict):
            return {k: _resolve(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_resolve(v) for v in val]
        return val

    return {k: _resolve(v) for k, v in inputs.items()}


def _tool_to_read(tool_dict: dict[str, Any]) -> ToolRead:
    """Convert a raw tool dict to a ToolRead Pydantic model."""
    from datetime import datetime, timezone
    
    now = datetime.now(timezone.utc)
    return ToolRead(
        id=tool_dict.get("id", ""),
        name=tool_dict.get("name", ""),
        description=tool_dict.get("description", ""),
        purpose=tool_dict.get("purpose", ""),
        tool_type=tool_dict.get("tool_type", "http_api"),
        endpoint_url=tool_dict.get("endpoint_url", ""),
        mcp_server_url=tool_dict.get("mcp_server_url", ""),
        http_method=tool_dict.get("http_method", "GET"),
        auth_type=tool_dict.get("auth_type", "none"),
        auth_ref=tool_dict.get("auth_ref", ""),
        input_schema=tool_dict.get("input_schema", {}),
        output_schema=tool_dict.get("output_schema", {}),
        validation_rules=tool_dict.get("validation_rules", {}),
        examples=tool_dict.get("examples", []),
        tags=tool_dict.get("tags", []),
        category=tool_dict.get("category", "general"),
        requires_approval=tool_dict.get("requires_approval", False),
        risk_level=tool_dict.get("risk_level", "low"),
        enabled=tool_dict.get("enabled", True),
        rate_limit_per_minute=tool_dict.get("rate_limit_per_minute"),
        version=tool_dict.get("version", 1),
        tenant_public=tool_dict.get("tenant_public", False),
        idempotent=tool_dict.get("idempotent", False),
        embedding=tool_dict.get("embedding"),
        created_at=tool_dict.get("created_at", now.isoformat()),
        updated_at=tool_dict.get("updated_at", now.isoformat()),
    )


async def tool_executor(
    state: dict[str, Any],
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Execute a single DAG task with optional speculative execution.

    If the task has multiple ``approaches`` (list of dicts with tool_name + inputs),
    they are raced in parallel via speculative execution.  Otherwise, a single
    approach is constructed from the task's ``tool_name`` and ``inputs``.

    This node is invoked via ``Send()`` from ``route_dag``.  It receives
    a slice of state containing just the task and its context.

    Returns:
        Dict with ``tool_results`` (single entry) and ``dag_results`` update.
    """
    task: dict[str, Any] = state.get("task", {})
    available_tools: list[dict[str, Any]] = state.get("available_tools", [])
    dag_results: dict[str, Any] = state.get("dag_results", {})
    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    task_id: str = task.get("id", "unknown")
    dag_generation: int = state.get("_dag_generation", 0)

    if session_factory:
        async with session_factory() as session:
            return await _execute_task(session, task, available_tools, dag_results, gathered, task_id, dag_generation)
    return await _execute_task(None, task, available_tools, dag_results, gathered, task_id, dag_generation)


async def _execute_task(
    session: Any,
    task: dict[str, Any],
    available_tools: list[dict[str, Any]],
    dag_results: dict[str, Any],
    gathered: dict[str, Any],
    task_id: str,
    dag_generation: int = 0,
) -> dict[str, Any]:
    """Execute a single DAG task — extracted for proper session management."""
    approaches: list[dict[str, Any]] = task.get("approaches", [])
    if approaches:
        adapt = get_settings().agent.adaptive_reflection
        logger.info("tool_executor.speculative", task_id=task_id, count=len(approaches))
        result = await _speculative_execute(
            approaches, available_tools, dag_results, gathered, task_id,
            max_approaches=adapt.max_speculative_approaches,
            timeout=adapt.speculative_timeout_s,
            session=session,
        )
        result["_dag_generation"] = dag_generation
        return {
            "tool_results": [result],
            "dag_results": {**dag_results, task_id: result.get("data")},
            "completed_task_ids": [task_id],
            "_tool_executed_in_turn": True if result.get("tool_name") else False,
        }

    single_approach = {
        "tool_name": task.get("tool_name"),
        "inputs": task.get("inputs", {}),
    }
    if single_approach["tool_name"]:
        result = await _execute_single_approach(
            single_approach, available_tools, dag_results, gathered, task_id,
            session=session,
        )
    else:
        result = {"tool_name": None, "status": "success", "data": None, "error": None, "task_id": task_id}
    result["_dag_generation"] = dag_generation

    return {
        "tool_results": [result],
        "dag_results": {**dag_results, task_id: result.get("data")},
        "completed_task_ids": [task_id],
        "_tool_executed_in_turn": True if result.get("tool_name") else False,
    }
