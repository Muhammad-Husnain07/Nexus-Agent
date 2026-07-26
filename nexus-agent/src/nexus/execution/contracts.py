"""Output Contract Validator — dynamically evaluates API response shape against registry contracts.

Reads ``output_contract`` from the capability registry and validates
tool results against it. Uses dot-path key resolution (no ``jsonpath-ng``
dependency — reuses the same pattern as ``concurrent_executor._deep_get``).

No hardcoded field names, no hardcoded validation logic.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.registry.client import RegistryClient

logger = structlog.get_logger("nexus.execution.contracts")


class OutputContractError(Exception):
    """Raised when a tool response fails output contract validation."""


async def validate_tool_result(
    capability: str,
    result_data: dict[str, Any] | None,
    registry: RegistryClient,
) -> tuple[bool, str]:
    """Validate a tool result against the capability's output contract.

    Args:
        capability: The logical operation name (e.g. ``"get_weather"``).
        result_data: The parsed response dict from the tool call.
        registry: ``RegistryClient`` for DB-backed contract metadata.

    Returns:
        A tuple of ``(is_valid, reason)``. If valid, ``reason`` is empty.
    """
    if result_data is None:
        return False, "No result data returned"

    contract = await registry.get_output_contract(capability)
    if not contract:
        return True, ""

    # Check required_any_of: at least one JSON-like path must exist in data
    required_any_of = contract.get("required_any_of", [])
    if required_any_of:
        for path in required_any_of:
            # Remove leading "$." if present (JSONPath notation)
            clean_path = path
            if clean_path.startswith("$."):
                clean_path = clean_path[2:]
            if _path_exists(result_data, clean_path):
                return True, ""

        return False, (
            f"Output contract failed for '{capability}': "
            f"none of {required_any_of} found in response"
        )

    return True, ""


def _path_exists(data: dict[str, Any], path: str) -> bool:
    """Check if a dot-separated path exists in a nested dict.

    Handles:
    - Simple keys: ``current_weather``
    - Nested: ``results[0].latitude`` (bracket index notation)
    """
    current: Any = data
    parts = path.split(".")
    for segment in parts:
        # Handle bracket notation: results[0]
        if "[" in segment and segment.endswith("]"):
            key, idx_str = segment[:-1].split("[", 1)
            idx = int(idx_str)
            if key:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return False
            if isinstance(current, list) and idx < len(current):
                current = current[idx]
            elif idx == 0 and isinstance(current, dict):
                pass  # [0] on a dict means "first match"
            else:
                return False
        else:
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            else:
                return False
    return True
