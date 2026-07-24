"""Shared I/O schema dependency analysis — used by router and planner.

Pure Python, deterministic. No LLM.

Analyzes tool I/O schemas to find dependencies: if Tool A produces
a field that Tool B requires as input, A must execute before B.
"""

from __future__ import annotations

from typing import Any


def build_signatures(tools: list[dict[str, Any]]) -> dict[str, tuple[set[str], set[str]]]:
    """Build I/O signature map: tool_name -> (required_inputs, output_fields).

    Pure Python extraction from tool schemas. No hardcoded field names.
    """
    signatures: dict[str, tuple[set[str], set[str]]] = {}
    for t in tools:
        name = t.get("name", "")
        if not name:
            continue
        inp = t.get("input_schema", {})
        out = t.get("output_schema", {})
        required = set(inp.get("required", [])) if isinstance(inp, dict) else set()
        outputs = set(out.get("properties", {}).keys()) if isinstance(out, dict) else set()
        signatures[name] = (required, outputs)
    return signatures


def analyze_dependencies(
    tools: list[dict[str, Any]],
    tool_subset: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Analyze I/O schemas to discover explicit dependencies between tools.

    For each pair of tools (A, B), check if any output field of A matches
    a required input field of B. If so, A -> B is a dependency.

    Args:
        tools: Full list of available tool definitions.
        tool_subset: If provided, only consider dependencies among these tools.
            Uses all tools by default.

    Returns:
        List of (prerequisite, dependent) tuples.
    """
    signatures = build_signatures(tools)
    dependencies: list[tuple[str, str]] = []

    for name_b, (inputs_b, _) in signatures.items():
        if tool_subset is not None and name_b not in tool_subset:
            continue
        for name_a, (_, outputs_a) in signatures.items():
            if name_a == name_b:
                continue
            if tool_subset is not None and name_a not in tool_subset:
                continue
            shared = inputs_b & outputs_a
            if shared:
                dependencies.append((name_a, name_b))

    return dependencies


def has_schema_dependency(
    matched_tools: set[str],
    all_tools: list[dict[str, Any]],
) -> bool:
    """Check if any tool in the matched set has a required input that
    another matched tool produces as output.

    Lightweight check (only considers ``matched_tools``, not all tools).
    """
    deps = analyze_dependencies(all_tools, tool_subset=matched_tools)
    return len(deps) > 0


def find_unmet_inputs(
    tool_name: str,
    all_tools: list[dict[str, Any]],
) -> set[str]:
    """Find required inputs for a tool that no other tool produces.

    Returns:
        Set of field names that are required but not provided by any tool's output.
    """
    signatures = build_signatures(all_tools)
    reqs, _ = signatures.get(tool_name, (set(), set()))

    all_outputs: set[str] = set()
    for name, (_, outs) in signatures.items():
        if name != tool_name:
            all_outputs |= outs

    return reqs - all_outputs
