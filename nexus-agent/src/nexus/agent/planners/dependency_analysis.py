"""Shared I/O schema dependency analysis — used by router and planner.

Pure Python, deterministic. No LLM.

Analyzes tool I/O schemas to find dependencies: if Tool A produces
a field that Tool B requires as input, A must execute before B.
"""

from __future__ import annotations

from typing import Any


def build_signatures(tools: list[dict[str, Any]]) -> dict[str, tuple[set[str], set[str], set[str], set[str]]]:
    """Build I/O signature map: tool_name -> (required_inputs, output_fields,
    consumed_artifacts, produced_artifacts).

    Required inputs / output fields come from the tool schemas; consumed and
    produced artifacts come from the tool's declarative ``consumes`` /
    ``produces`` metadata (artifact names, not schema fields). Pure Python
    extraction, no hardcoded field names.
    """
    signatures: dict[str, tuple[set[str], set[str], set[str], set[str]]] = {}
    for t in tools:
        name = t.get("name", "")
        if not name:
            continue
        inp = t.get("input_schema", {})
        out = t.get("output_schema", {})
        required = set(inp.get("required", [])) if isinstance(inp, dict) else set()
        outputs = set(out.get("properties", {}).keys()) if isinstance(out, dict) else set()
        consumes = {str(a) for a in (t.get("consumes") or [])}
        produces = {str(a) for a in (t.get("produces") or [])}
        signatures[name] = (required, outputs, consumes, produces)
    return signatures


def analyze_dependencies(
    tools: list[dict[str, Any]],
    tool_subset: set[str] | None = None,
) -> list[tuple[str, str]]:
    """Discover explicit dependencies between tools.

    Two metadata-driven signals are combined (union):
    1. **Schema**: an output field of A matches a required input field of B.
    2. **Artifact metadata**: A declares ``produces`` an artifact that B
       declares as ``consumes`` — the planner's explicit upstream/downstream
       contract, independent of field names.

    If both signals fire for the same pair, the dependency is emitted once.

    Args:
        tools: Full list of available tool definitions.
        tool_subset: If provided, only consider dependencies among these tools.
            Uses all tools by default.

    Returns:
        List of (prerequisite, dependent) tuples.
    """
    signatures = build_signatures(tools)
    dependencies: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for name_b, (inputs_b, _, consumes_b, _) in signatures.items():
        if tool_subset is not None and name_b not in tool_subset:
            continue
        for name_a, (_, outputs_a, _, produces_a) in signatures.items():
            if name_a == name_b:
                continue
            if tool_subset is not None and name_a not in tool_subset:
                continue
            if (inputs_b & outputs_a) or (consumes_b & produces_a):
                pair = (name_a, name_b)
                if pair not in seen:
                    seen.add(pair)
                    dependencies.append(pair)

    return dependencies


def has_schema_dependency(matched_tools: set[str]) -> bool:
    """Check if any tool in the matched set has a required input that
    another matched tool produces as output.

    Reads capability metadata from GlobalContext (no state dependency).
    """
    if not matched_tools:
        return False

    from nexus.context.global_context import get_global_context
    gc = get_global_context()
    if not gc or not hasattr(gc, "compiled_graph") or not gc.compiled_graph:
        return False

    # Serialize CompiledCapabilityNode objects to dicts via to_dict()
    all_tools = [node.to_dict() for node in gc.compiled_graph.nodes.values()]

    deps = analyze_dependencies(all_tools, tool_subset=matched_tools)
    return len(deps) > 0


def find_unmet_inputs(
    tool_name: str,
    all_tools: list[dict[str, Any]],
) -> set[str]:
    """Find required inputs for a tool that no other tool provides.

    Combines both signals: schema-required fields not in any tool's output
    schema, plus declared ``consumes`` artifacts not in any tool's
    ``produces`` metadata.

    Returns:
        Set of field/artifact names that are required but not provided.
    """
    signatures = build_signatures(all_tools)
    reqs, _, consumes, _ = signatures.get(tool_name, (set(), set(), set(), set()))

    all_outputs: set[str] = set()
    all_produces: set[str] = set()
    for name, (_, outs, _, produces) in signatures.items():
        if name != tool_name:
            all_outputs |= outs
            all_produces |= produces

    return (reqs - all_outputs) | (consumes - all_produces)
