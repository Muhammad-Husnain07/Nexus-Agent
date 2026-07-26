"""Dependency Simplification — inlines pass-through physical nodes.

A pass-through node takes a single input and produces the same output
without transformation. This pass detects such nodes and rewires
``depends_on`` references to skip the intermediate node.

Pass is pure: no I/O, no datetime, no random.
"""

from nexus.compiler.ir_models import ExecutionGraph, PhysicalNode, ToolNode


def run(graph: ExecutionGraph) -> ExecutionGraph:
    """Simplify the dependency graph by inlining pass-through nodes.

    Args:
        graph: The current ``ExecutionGraph`` with physical nodes.

    Returns:
        ``ExecutionGraph`` with simplified dependencies.
    """
    nodes = graph.nodes
    if len(nodes) < 2:
        return graph

    pass_through_ids: set[str] = set()
    for nid, node in nodes.items():
        if isinstance(node, ToolNode):
            if _is_pass_through(node):
                pass_through_ids.add(nid)

    if not pass_through_ids:
        return graph

    kept: dict[str, PhysicalNode] = {}
    for nid, node in nodes.items():
        if nid in pass_through_ids:
            continue
        new_deps = []
        for dep_id in node.depends_on:
            if dep_id in pass_through_ids:
                pt_node = nodes.get(dep_id)
                if pt_node:
                    new_deps.extend(pt_node.depends_on)
            else:
                new_deps.append(dep_id)
        kept[nid] = _rewire_deps(node, new_deps)

    if len(kept) == len(nodes):
        return graph

    new_waves = _prune_waves(graph.waves, set(kept.keys()))
    return graph.model_copy(update={"nodes": kept, "waves": new_waves})


def _is_pass_through(node: ToolNode) -> bool:
    """Check if a ToolNode is a pass-through (input keys match output refs).

    A ToolNode is a pass-through if its ``symbolic_ref`` appears as an
    input key, meaning no transformation occurred.
    """
    return node.symbolic_ref in node.inputs


def _rewire_deps(node: PhysicalNode, new_deps: list[str]) -> PhysicalNode:
    """Return a new node with updated depends_on list."""
    return node.model_copy(update={"depends_on": new_deps})


def _prune_waves(waves: list[list[str]], kept_ids: set[str]) -> list[list[str]]:
    """Remove pass-through node IDs from wave lists."""
    pruned = []
    for wave in waves:
        kept_wave = [nid for nid in wave if nid in kept_ids]
        if kept_wave:
            pruned.append(kept_wave)
    return pruned
