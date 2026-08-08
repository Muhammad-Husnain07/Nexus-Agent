"""Candidate Ranking — attaches ranked alternative endpoints to each ToolNode.

This pass runs after the resolver attaches a single best endpoint.
It enriches each ToolNode with a ``candidate_endpoints`` list — ordered
alternatives for the same capability that the executor can fall back to
if the primary endpoint fails validation.

The pass reads ``candidate_endpoints`` from ToolNode metadata if already
set by the Compiler, and ensures every ToolNode carries at least its
primary endpoint as a candidate (so the executor always has a fallback).

Pass is pure: no I/O, no datetime, no random.
"""

from __future__ import annotations

from nexus.compiler.ir_models import ExecutionGraph, MapNode, ToolNode

# Runs second — candidate endpoints must exist before fusion/dedup decide.
PRIORITY = 20


def run(graph: ExecutionGraph) -> ExecutionGraph:
    """Attach candidate_endpoints to every ToolNode.

    If a ToolNode already has candidate_endpoints (set by the resolver),
    the pass ensures the primary endpoint is included at position 0.
    If no candidates exist, creates a singleton list from the current
    endpoint metadata.

    Args:
        graph: The current ExecutionGraph.

    Returns:
        ExecutionGraph with candidate_endpoints populated on all ToolNodes.
    """
    nodes = graph.nodes
    modified = False

    for _nid, node in nodes.items():
        candidates: list[dict] = []

        if isinstance(node, ToolNode):
            candidates = _ensure_candidates(node)
            if candidates != node.candidate_endpoints:
                node.candidate_endpoints = candidates
                modified = True

        elif isinstance(node, MapNode):
            candidates = _ensure_candidates(node.body)
            if candidates != node.body.candidate_endpoints:
                node.body.candidate_endpoints = candidates
                modified = True

    if not modified:
        return graph

    data = graph.model_dump()
    data.pop("nodes", None)
    return ExecutionGraph(**data, nodes=nodes)


def _ensure_candidates(tool: ToolNode) -> list[dict]:
    """Build a candidate list with the primary endpoint always at position 0."""
    primary = {
        "endpoint_id": "",
        "capability": tool.capability,
        "provider_name": tool.tool_name,
        "url": tool.endpoint_url,
        "http_method": tool.http_method,
        "score": 1.0,
        "cost_per_call": tool.cost_estimate,
        "latency_p99_ms": tool.latency_estimate_ms,
        "reliability_score": 1.0,
    }

    existing = list(tool.candidate_endpoints) if tool.candidate_endpoints else []
    merged: list[dict] = [primary]

    for cand in existing:
        url = cand.get("url", "")
        if url and url != tool.endpoint_url and not any(
            c.get("url") == url for c in merged
        ):
            merged.append(cand)

    return merged
