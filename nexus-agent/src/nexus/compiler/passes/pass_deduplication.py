"""Pass Deduplication — merges ToolNodes with identical tool_name + inputs.

Deduplicates by hashing ``(tool_name, sorted(inputs))`` for each ``ToolNode``.
When duplicates are found, one is kept and all ``depends_on`` references to
the removed duplicates are remapped to the kept node.

Pass is pure: no I/O, no datetime, no random.
"""

import hashlib
import json

from nexus.compiler.ir_models import (
    ConditionalNode,
    ExecutionGraph,
    MapNode,
    PhysicalNode,
    ReduceNode,
    ToolNode,
)

# Merges duplicate nodes — runs after constraint ordering, before
# elimination/fusion so downstream passes see a deduplicated node set.
PRIORITY = 40


def run(graph: ExecutionGraph) -> ExecutionGraph:
    """Merge duplicate ToolNodes and remap dependency references.

    Args:
        graph: The current ``ExecutionGraph`` with physical nodes.

    Returns:
        ``ExecutionGraph`` with duplicate ToolNodes merged.
    """
    nodes = graph.nodes
    if len(nodes) < 2:
        return graph

    # Build hash → list of (nid, ToolNode)
    sig_groups: dict[str, list[tuple[str, ToolNode]]] = {}
    for nid, node in nodes.items():
        tnode = _extract_tool_node(node)
        if tnode is None:
            continue
        sig = _node_signature(tnode)
        sig_groups.setdefault(sig, []).append((nid, tnode))

    # Build remapping: duplicate ID → canonical ID
    remap: dict[str, str] = {}
    for sig, group in sig_groups.items():
        if len(group) < 2:
            continue
        canonical = group[0][0]
        for nid, _tnode in group[1:]:
            remap[nid] = canonical

    if not remap:
        return graph

    # Build new node dict, skipping duplicates
    kept: dict[str, PhysicalNode] = {}
    for nid, node in nodes.items():
        if nid in remap:
            continue
        kept[nid] = _remap_deps(node, remap)

    # Handle MapNode bodies
    for nid, node in kept.items():
        if isinstance(node, MapNode) and node.body.id in remap:
            new_body = node.body.model_copy(
                update={"id": remap[node.body.id]},
            )
            kept[nid] = node.model_copy(update={"body": new_body})

    if len(kept) == len(nodes):
        return graph

    # Prune waves
    kept_ids = set(kept.keys())
    new_waves = []
    for wave in graph.waves:
        kept_wave = [nid for nid in wave if nid in kept_ids]
        if kept_wave:
            new_waves.append(kept_wave)

    data = graph.model_dump()
    data.pop("nodes", None)
    data.pop("waves", None)
    return ExecutionGraph(**data, nodes=kept, waves=new_waves)


def _extract_tool_node(node: PhysicalNode) -> ToolNode | None:
    """Extract a ToolNode from a PhysicalNode.
    
    For MapNode, returns its body ToolNode. For ToolNode, returns itself.
    For other types, returns None (cannot be deduped).
    """
    if isinstance(node, ToolNode):
        return node
    if isinstance(node, MapNode):
        return node.body
    return None


def _node_signature(tnode: ToolNode) -> str:
    """Deterministic hash of (tool_name, sorted inputs)."""
    payload = json.dumps(
        {"tool_name": tnode.tool_name, "inputs": tnode.inputs},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _remap_deps(node: PhysicalNode, remap: dict[str, str]) -> PhysicalNode:
    """Return a copy of node with depends_on IDs remapped."""
    new_deps = [remap.get(d, d) for d in node.depends_on]

    if isinstance(node, ConditionalNode):
        new_true = [remap.get(d, d) for d in node.branch_true]
        new_false = [remap.get(d, d) for d in node.branch_false]
        return node.model_copy(
            update={
                "depends_on": new_deps,
                "branch_true": new_true,
                "branch_false": new_false,
            },
        )

    if isinstance(node, ReduceNode):
        new_source = remap.get(node.source_ref, node.source_ref)
        return node.model_copy(
            update={"depends_on": new_deps, "source_ref": new_source},
        )

    return node.model_copy(update={"depends_on": new_deps})
