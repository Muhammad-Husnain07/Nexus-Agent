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


def run(graph: ExecutionGraph) -> ExecutionGraph:
    """Remove unreferenced pure nodes from the graph.

    Args:
        graph: The current ``ExecutionGraph`` with physical nodes.

    Returns:
        ``ExecutionGraph`` with dead pure nodes removed.
    """
    # Build set of node IDs that are referenced as dependencies
    referenced_ids: set[str] = set()
    for node in graph.nodes.values():
        for dep in node.depends_on:
            referenced_ids.add(dep)

    kept_nodes: dict = {}
    removed_count = 0

    for nid, node in graph.nodes.items():
        # NEVER delete ToolNode or MapNode — side-effectful API calls
        if isinstance(node, (ToolNode, MapNode)):
            kept_nodes[nid] = node
            continue

        # Pure nodes (Reduce, Conditional, unknown) kept only if referenced
        if nid in referenced_ids:
            kept_nodes[nid] = node
        else:
            removed_count += 1

    if removed_count == 0:
        return graph

    new_graph = graph.model_copy(deep=True)
    new_graph.nodes = kept_nodes
    new_graph.waves = _rebuild_waves(kept_nodes)
    return new_graph


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
