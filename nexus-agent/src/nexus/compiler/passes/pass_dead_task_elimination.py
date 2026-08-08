"""PassDeadTaskElimination — removes unreferenced pure computation nodes.

ToolNodes and MapNodes are NEVER eliminated because they represent
intentional, side-effectful API calls.  ReduceNodes and ConditionalNodes
can be eliminated if their outputs are not consumed by any downstream node.

Pass is pure: no I/O, no datetime, no random.
"""

from __future__ import annotations

from collections import deque

from nexus.compiler.ir_models import (
    ConditionalNode,
    ExecutionGraph,
    MapNode,
    ReduceNode,
    ToolNode,
)

# Eliminates unreferenced pure nodes — runs after dedup so duplicates are
# merged before elimination decides what is "dead".
PRIORITY = 50


def run(graph: ExecutionGraph) -> ExecutionGraph:
    """Remove unreferenced pure nodes from the graph.

    Args:
        graph: The current ``ExecutionGraph`` with physical nodes.

    Returns:
        ``ExecutionGraph`` with dead pure nodes removed.
    """
    # Build set of node IDs that are referenced as dependencies OR as
    # conditional branches (branch_true/branch_false are edges, not deps).
    referenced_ids: set[str] = set()
    for node in graph.nodes.values():
        for dep in node.depends_on:
            referenced_ids.add(dep)
        if isinstance(node, ConditionalNode):
            referenced_ids.update(node.branch_true)
            referenced_ids.update(node.branch_false)

    kept_nodes: dict = {}
    removed_count = 0

    for nid, node in graph.nodes.items():
        # NEVER delete ToolNode, MapNode, or ConditionalNode — side-effectful
        # API calls and control-flow gates are always kept.
        if isinstance(node, (ToolNode, MapNode, ConditionalNode)):
            kept_nodes[nid] = node
            continue

        # Pure nodes (Reduce, unknown) kept only if referenced
        if nid in referenced_ids:
            kept_nodes[nid] = node
        else:
            removed_count += 1

    if removed_count == 0:
        return graph

    # Immutable graph contract: rebuild a NEW graph (attribute assignment on
    # a frozen model raises).
    data = graph.model_dump()
    data.pop("nodes", None)
    data.pop("waves", None)
    return ExecutionGraph(
        **data,
        nodes=kept_nodes,
        waves=_rebuild_waves(kept_nodes),
    )


def _rebuild_waves(nodes: dict) -> list[list[str]]:
    """Topological sort — rebuild waves after node elimination.

    Pure: no I/O, no datetime, no random.  Uses Kahn's algorithm.
    """
    in_degree: dict[str, int] = {}
    children: dict[str, list[str]] = {}

    for nid, node in nodes.items():
        deps = getattr(node, "depends_on", []) or []
        in_degree[nid] = len(deps)
        for dep in deps:
            if dep in children:
                children[dep].append(nid)
            else:
                children[dep] = [nid]

    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    waves: list[list[str]] = []

    while queue:
        wave = list(queue)
        waves.append(wave)
        next_queue: deque[str] = deque()
        for nid in wave:
            for child in children.get(nid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_queue.append(child)
        queue = next_queue

    return waves
