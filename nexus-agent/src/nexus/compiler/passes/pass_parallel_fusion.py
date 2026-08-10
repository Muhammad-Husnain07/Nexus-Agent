"""Batch Fusion — fuses multiple MapNode tasks into a single batch ToolNode call.

When 5+ ``MapNode`` tasks iterate over a collection and target the same
endpoint with ``supports_batch=True``, they are fused into a single
``ToolNode`` that receives the full collection.

Pass is pure: no I/O, no datetime, no random.
"""

from nexus.compiler.ir_models import ExecutionGraph, PhysicalNode, ToolNode

# Last structural pass — fuses batches only after the node set is final.
PRIORITY = 70

_BATCH_FUSION_THRESHOLD: int = 5


def run(graph: ExecutionGraph) -> ExecutionGraph:
    """Fuse MapNode tasks targeting the same batched endpoint.

    Args:
        graph: The current ``ExecutionGraph`` with physical nodes.

    Returns:
        ``ExecutionGraph`` with fused batch nodes.
    """
    nodes = graph.nodes
    if len(nodes) < _BATCH_FUSION_THRESHOLD:
        return graph

    from nexus.compiler.ir_models import MapNode

    # Collect MapNodes by (tool_name, iterate_over)
    batches: dict[tuple[str, str], list[tuple[str, MapNode]]] = {}
    for nid, node in nodes.items():
        if isinstance(node, MapNode):
            key = (node.body.tool_name, node.iterate_over)
            batches.setdefault(key, []).append((nid, node))

    if not batches:
        return graph

    fused: dict[str, PhysicalNode] = dict(nodes)
    for key, group in batches.items():
        if len(group) < _BATCH_FUSION_THRESHOLD:
            continue

        tool_name, iterate_over = key
        # D4/P0-D: fusion is ONLY legal when the endpoint declares
        # supports_batch (absent metadata = no fusion — never change
        # execution semantics merely to make the graph smaller).
        if not _endpoint_supports_batch(tool_name):
            continue

        first_id, first_node = group[0]

        combined_deps: set[str] = set()
        all_inputs: dict[str, list] = {}
        for _nid, mnode in group:
            combined_deps.update(mnode.depends_on)
            for k, v in mnode.body.inputs.items():
                all_inputs.setdefault(k, []).append(v)

        fused_node = ToolNode(
            id=first_id,
            symbolic_ref=first_node.symbolic_ref,
            capability=first_node.body.capability,
            tool_name=tool_name,
            inputs={"items": all_inputs, "iterate_over": iterate_over},
            depends_on=sorted(combined_deps),
        )

        fused[first_id] = fused_node
        for nid, _mnode in group[1:]:
            del fused[nid]

    if len(fused) == len(nodes):
        return graph

    new_waves = _prune_waves(graph.waves, set(fused.keys()))
    return graph.model_copy(update={"nodes": fused, "waves": new_waves})


def _endpoint_supports_batch(tool_name: str) -> bool:
    """D4/P0-D: fusion requires the endpoint's ``supports_batch`` metadata.

    Reads the capability's provider endpoints from GlobalContext. Absent
    metadata (or any failure) → False → no fusion (the safe default: the
    optimizer never changes execution semantics without proof).
    """
    try:
        from nexus.context.global_context import get_global_context

        gc = get_global_context()
        for prov in (gc.capability_providers or {}).get(tool_name, []) or []:
            if not isinstance(prov, dict):
                continue
            for ep in (prov.get("endpoints") or []):
                if isinstance(ep, dict) and ep.get("supports_batch"):
                    return True
    except Exception:
        return False
    return False


def _prune_waves(waves: list[list[str]], kept_ids: set[str]) -> list[list[str]]:
    """Remove fused-out node IDs from wave lists."""
    pruned = []
    for wave in waves:
        kept_wave = [nid for nid in wave if nid in kept_ids]
        if kept_wave:
            pruned.append(kept_wave)
    return pruned
