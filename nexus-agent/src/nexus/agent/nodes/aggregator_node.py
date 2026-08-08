"""AggregatorNode — pure Python execution of ReduceNode operations.

After the ExecutorNode finishes tool calls, this node processes any
``ReduceNode`` nodes in the graph: sorts, groups, averages, filters,
top-k selections, and summary aggregations.

Operates on the ``_executor_results`` from state.
"""

from __future__ import annotations

import statistics
from typing import Any

import structlog

from nexus.agent.node_wrapper import context_node
from nexus.compiler.ir_models import ExecutionGraph, ReduceNode
from nexus.execution.context import ExecutionContext, StatePatch

logger = structlog.get_logger("nexus.agent.nodes.aggregator")


@context_node
async def aggregator_node(ctx: ExecutionContext) -> StatePatch:
    """Execute all ReduceNode operations in the graph."""
    snapshot = ctx.snapshot
    graph_data = snapshot.get("_execution_graph")
    tool_results_data = snapshot.get("tool_results", [])
    executor_results = {r.get("task_id", ""): r for r in tool_results_data if isinstance(r, dict)}
    collections = snapshot.get("_collections", {})

    if graph_data is None:
        return StatePatch(version=ctx.version + 1, updates={"_aggregated_results": {}})

    graph = graph_data
    if isinstance(graph_data, dict):
        graph = ExecutionGraph(**graph_data)

    aggregated: dict[str, Any] = {}
    for nid, node in graph.nodes.items():
        if not isinstance(node, ReduceNode):
            continue

        source_data = _resolve_source(node.source_ref, collections, executor_results)
        if not source_data:
            logger.warning("aggregator_node.empty_source", ref=node.source_ref, node=nid)
            continue

        result = _execute_reduce(node, source_data)
        aggregated[nid] = result
        logger.info(
            "aggregator_node.reduce_ok",
            node=nid,
            kind=node.aggregate_kind,
            items=len(result) if isinstance(result, list) else 1,
        )

    return StatePatch(
        version=ctx.version + 1,
        updates={"_aggregated_results": aggregated},
    )


def _resolve_source(ref: str, collections: dict, results: dict) -> list:
    """Resolve a ReduceNode source_ref to a list of items."""
    if ref in collections:
        items = collections[ref]
        if isinstance(items, list):
            return items
        return [items]

    if ref in results:
        data = results[ref].get("data", []) if isinstance(results[ref], dict) else []
        if isinstance(data, list):
            return data
        return [data]

    for _tid, tres in results.items():
        if isinstance(tres, dict):
            tdata = tres.get("data", {})
            if isinstance(tdata, dict) and ref in tdata:
                val = tdata[ref]
                if isinstance(val, list):
                    return val
                return [val]
    return []


def _execute_reduce(node: ReduceNode, data: list[dict]) -> Any:
    """Execute a single ReduceNode aggregation."""
    if not data:
        return []

    kind = node.aggregate_kind
    key = node.key_path
    predicate = node.predicate
    limit = node.limit

    if kind == "sort":
        return _reduce_sort(data, key, limit)
    if kind == "group_by":
        return _reduce_group_by(data, key)
    if kind == "average":
        return _reduce_average(data, key)
    if kind == "top_k":
        return _reduce_top_k(data, key, limit or 5)
    if kind == "filter":
        return _reduce_filter(data, predicate)
    if kind == "summary":
        return _reduce_summary(data)
    return data


def _deep_val(item: Any, path: str) -> Any:
    """Resolve a dot-separated path in a nested dict."""
    if not path:
        return item
    parts = path.split(".")
    current = item
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            idx = int(part) if part.isdigit() else None
            if idx is not None and idx < len(current):
                current = current[idx]
            else:
                return None
        else:
            return None
    return current


def _reduce_sort(data: list[dict], key: str, limit: int | None) -> list[dict]:
    """Sort data by a key, optionally limited."""
    if not key:
        return data[:limit] if limit else data
    sorted_data = sorted(data, key=lambda x: _deep_val(x, key) or "")
    return sorted_data[:limit] if limit else sorted_data


def _reduce_group_by(data: list[dict], key: str) -> dict[str, list[dict]]:
    """Group data by a key."""
    groups: dict[str, list[dict]] = {}
    for item in data:
        val = str(_deep_val(item, key) or "unknown")
        groups.setdefault(val, []).append(item)
    return groups


def _reduce_average(data: list[dict], key: str) -> float:
    """Compute average of a numeric key."""
    values = []
    for item in data:
        val = _deep_val(item, key)
        if val is not None:
            try:
                values.append(float(val))
            except (ValueError, TypeError):
                continue
    if not values:
        return 0.0
    return statistics.mean(values)


def _reduce_top_k(data: list[dict], key: str, k: int) -> list[dict]:
    """Return top-k items by a numeric key (descending)."""
    if not key:
        return data[:k]
    scored = []
    for item in data:
        val = _deep_val(item, key)
        try:
            scored.append((float(val) if val is not None else 0.0, item))
        except (ValueError, TypeError):
            scored.append((0.0, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _score, item in scored[:k]]


def _reduce_filter(data: list[dict], predicate: str) -> list[dict]:
    """Filter data by a simple predicate expression."""
    if not predicate:
        return data
    parts = predicate.split("=", 1)
    if len(parts) != 2:
        return data
    field_path, expected = parts[0].strip(), parts[1].strip()
    negate = field_path.endswith("!")
    if negate:
        field_path = field_path[:-1].strip()

    results = []
    for item in data:
        val = str(_deep_val(item, field_path) or "")
        if negate:
            if val != expected:
                results.append(item)
        else:
            if val == expected:
                results.append(item)
    return results


def _reduce_summary(data: list[dict]) -> dict:
    """Generate a summary: count, keys present, sample values."""
    if not data:
        return {"count": 0, "keys": [], "sample": None}
    first = data[0]
    keys = list(first.keys()) if isinstance(first, dict) else []
    return {"count": len(data), "keys": keys, "sample": first}
