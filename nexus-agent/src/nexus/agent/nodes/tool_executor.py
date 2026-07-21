"""tool_executor node — execute a single DAG task directly (no LLM).

Receives a task slice via ``Send()`` with the task definition and
available tools.  Resolves placeholders, validates inputs, makes the
HTTP call, and returns the result — all without any LLM call.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from httpx import AsyncClient

from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.agent.nodes.tool_executor")


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
) -> dict[str, Any]:
    """Execute a single DAG task and return the result.

    This node is invoked via ``Send()`` from ``route_dag``.  It receives
    a slice of state containing just the task and its context.

    Returns:
        Dict with ``tool_results`` (single entry) and ``dag_results`` update.
    """
    task: dict[str, Any] = state.get("task", {})
    available_tools: list[dict[str, Any]] = state.get("available_tools", [])
    dag_results: dict[str, Any] = state.get("dag_results", {})
    gathered: dict[str, Any] = state.get("gathered_requirements", {})

    tool_name: str | None = task.get("tool_name")
    task_id: str = task.get("id", "unknown")
    logger.info("tool_executor.received", task_id=task_id, tool=tool_name, dag_keys=list(dag_results.keys()))

    if not tool_name:
        logger.info("tool_executor.no_tool", task_id=task_id)
        return {
            "tool_results": [{"tool_name": None, "status": "success", "data": None, "error": None, "task_id": task_id}],
            "dag_results": {task_id: None},
        }

    tool_dict = _find_tool(tool_name, available_tools)
    if not tool_dict:
        logger.warning("tool_executor.tool_not_found", task_id=task_id, tool_name=tool_name)
        return {
            "tool_results": [{"tool_name": tool_name, "status": "error", "data": None, "error": f"Tool '{tool_name}' not found", "task_id": task_id}],
            "dag_results": {task_id: None},
        }

    raw_inputs: dict[str, Any] = task.get("inputs", {})
    resolved_inputs = _resolve_placeholders(raw_inputs, dag_results, gathered)

    try:
        tool_read = _tool_to_read(tool_dict)
        executor = ToolExecutor()
        context = ExecutionContext(session_id=state.get("session_id", ""), agent_run_id="")

        result: ToolResult = await executor.execute(
            tool_read,
            resolved_inputs,
            context,
            skip_approval=True,
            session=None,
        )

        result_data = result.data if result.status == "success" else None
        error = result.error if result.status != "success" else None

        # Treat responses with only metadata keys as empty (no meaningful data)
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
                # Check if response has only metadata keys (no data)
                non_meta = [k for k in result_data if k not in _META_KEYS]
                if not has_data_key and not non_meta:
                    result_data = None
                    error = error or "API returned no data"

        logger.info("tool_executor.completed", task_id=task_id, tool=tool_name, status=result.status)

        return {
            "tool_results": [
                {
                    "tool_name": tool_name,
                    "status": result.status,
                    "data": result_data,
                    "error": error,
                    "task_id": task_id,
                    "duration_ms": result.duration_ms,
                }
            ],
            "dag_results": {task_id: result_data},
        }
    except Exception as exc:
        logger.error("tool_executor.failed", task_id=task_id, tool=tool_name, error=str(exc))
        return {
            "tool_results": [
                {
                    "tool_name": tool_name,
                    "status": "error",
                    "data": None,
                    "error": str(exc),
                    "task_id": task_id,
                }
            ],
            "dag_results": {task_id: None},
        }
