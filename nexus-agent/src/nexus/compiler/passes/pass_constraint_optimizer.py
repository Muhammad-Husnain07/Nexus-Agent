"""Constraint Optimizer — reorders execution waves for optimal throughput.

Groups ToolNodes by ``tool_name`` within waves to maximize connection reuse
and minimize provider switching overhead. Nodes with the same tool are
scheduled consecutively to improve cache locality and reduce connection churn.

This pass runs AFTER dead branch elimination, dependency simplification,
and batch fusion.

Pass is pure: no I/O, no datetime, no random.
"""

from collections import Counter

from nexus.compiler.ir_models import ExecutionGraph, PhysicalNode, ToolNode

# Reorders waves only — runs BEFORE passes that mutate the node set
# (dedup/fusion/elimination) so their wave rebuilds start from a
# well-ordered base.
PRIORITY = 30


def run(graph: ExecutionGraph) -> ExecutionGraph:
    """Re-order waves so nodes sharing the same tool execute consecutively.

    Args:
        graph: The current ``ExecutionGraph`` with physical nodes.

    Returns:
        ``ExecutionGraph`` with optimized wave ordering.
    """
    nodes = graph.nodes
    if not nodes or not graph.waves:
        return graph

    optimized_waves: list[list[str]] = []
    for wave in graph.waves:
        tool_groups: dict[str, list[str]] = {}
        for nid in wave:
            node = nodes.get(nid)
            if node is None:
                continue
            tool_key = _tool_group_key(node)
            tool_groups.setdefault(tool_key, []).append(nid)

        reordered = []
        for _tool_key, nids in tool_groups.items():
            reordered.extend(nids)
        optimized_waves.append(reordered)

    if optimized_waves == graph.waves:
        return graph

    data = graph.model_dump()
    data.pop("waves", None)
    return ExecutionGraph(**data, waves=optimized_waves)


def _tool_group_key(node: PhysicalNode) -> str:
    """Return a grouping key based on tool/provider affinity.

    For ToolNodes, the group is ``tool_name``. For other node types,
    a generic key is returned so they are not unnecessarily split.
    """
    if isinstance(node, ToolNode):
        return node.tool_name
    return f"__non_tool_{node.kind}__"
