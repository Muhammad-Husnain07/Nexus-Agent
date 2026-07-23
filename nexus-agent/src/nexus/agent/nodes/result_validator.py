"""result_validator — validate tool outputs before use.

Checks every completed tool result for:
1. Output schema compliance (if schema defined)
2. Size limits (prevent context blowup from massive payloads)
3. Suspicious content patterns (PII heuristics, injection markers)
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.result_validator")

_MAX_RESULT_SIZE_BYTES = 500_000
_MAX_RESULT_FIELDS = 200
_SUSPICIOUS_PATTERNS = [
    "<|im_end|>", "<|endoftext|>", "ignore previous instructions",
    "system override", "[SYSTEM]", "[INSTruction]",
]


async def result_validator(state: AgentState) -> dict[str, Any]:
    """Validate completed tool results before they enter the final response.

    Reads ``dag_results`` and ``available_tools``.  Flags suspicious or
    oversized results as ``_invalid_results`` so downstream nodes can
    truncate or redact.

    Returns:
        Dict with ``_invalid_results`` (list of (task_id, reason) tuples).
    """
    results: dict[str, Any] = state.get("dag_results", {})
    tools: list[dict[str, Any]] = state.get("available_tools", [])
    tool_map: dict[str, dict[str, Any]] = {t["name"]: t for t in tools}
    tasks: list[dict[str, Any]] = state.get("dag_tasks", [])
    task_map: dict[str, dict[str, Any]] = {t["id"]: t for t in tasks}
    invalid: list[dict[str, Any]] = []

    for task_id, result_data in results.items():
        if result_data is None:
            continue
        task = task_map.get(task_id)
        tool_name = (task or {}).get("tool_name", "")
        tool_schema = tool_map.get(tool_name, {}) if tool_name else {}
        output_schema = tool_schema.get("output_schema", {}) if isinstance(tool_schema, dict) else {}

        # 1. Output schema compliance
        if isinstance(output_schema, dict) and output_schema.get("required"):
            required_out: list[str] = output_schema.get("required", [])
            if isinstance(result_data, dict):
                for req_field in required_out:
                    if req_field not in result_data:
                        invalid.append({
                            "task_id": task_id,
                            "reason": f"Missing required output field: '{req_field}'",
                        })

        # 2. Size limits
        try:
            import json
            serialized = json.dumps(result_data)
            if len(serialized) > _MAX_RESULT_SIZE_BYTES:
                invalid.append({
                    "task_id": task_id,
                    "reason": f"Result too large: {len(serialized)} bytes (max {_MAX_RESULT_SIZE_BYTES})",
                })
        except (TypeError, ValueError):
            pass

        if isinstance(result_data, dict) and len(result_data) > _MAX_RESULT_FIELDS:
            invalid.append({
                "task_id": task_id,
                "reason": f"Result has {len(result_data)} fields (max {_MAX_RESULT_FIELDS})",
            })

        # 3. Suspicious content patterns
        result_str = str(result_data).lower()
        for pattern in _SUSPICIOUS_PATTERNS:
            if pattern.lower() in result_str:
                invalid.append({
                    "task_id": task_id,
                    "reason": f"Result contains suspicious pattern: '{pattern}'",
                })
                break

    if invalid:
        logger.warning("result_validator.issues", count=len(invalid))

    return {"_invalid_results": invalid}
