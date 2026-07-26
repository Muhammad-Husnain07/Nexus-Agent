"""Deterministic Compiler — translates LogicalWorkflow into ExecutionGraph.

The Compiler is the bridge between the LLM Semantic Planner (which produces a
LogicalWorkflow) and the Optimizer/Executor (which consume an ExecutionGraph).

Key responsibilities:
1. **Tool Resolution** — delegates to ``CapabilityResolver`` to find the optimal
   physical endpoint for each logical operation.
2. **Dependency Mapping** — converts logical ``ref``-based dependency references
   to physical node ``id``-based references.
3. **Wave Construction** — topological sort (Kahn's algorithm) produces
   execution waves for the Executor.

The ``compile()`` method is async (resolver I/O) but all transformation logic
within it is pure — no datetime, no random, no side effects beyond the resolver.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from typing import Any

from nexus.compiler.ir_models import (
    ConditionalNode,
    ExecutionGraph,
    LogicalNode,
    LogicalWorkflow,
    MapNode,
    ToolNode,
)
from nexus.compiler.resolver import CapabilityResolver, CapabilityError


class CompilerError(Exception):
    """Raised when the Compiler cannot resolve a logical operation."""


class Compiler:
    """Deterministic compiler translating LogicalWorkflow → ExecutionGraph.

    Usage::

        resolver = CapabilityResolver(db_session)
        compiler = Compiler(resolver)
        graph = await compiler.compile(workflow)

    Pure: all ID generation uses SHA256 hashing, never ``uuid.uuid4()``.
    """

    def __init__(self, resolver: CapabilityResolver) -> None:
        self.resolver = resolver

    def _deterministic_id(self, *parts: str, length: int = 12) -> str:
        """Pure: generate a deterministic ID from any number of string parts.

        Same inputs always produce the same ID. No I/O, no datetime, no random.
        """
        raw = "::".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:length]

    async def compile(self, workflow: LogicalWorkflow) -> ExecutionGraph:
        """Translate a LogicalWorkflow into a complete ExecutionGraph.

        Steps:
        1. Create a deterministic mapping from logical refs to physical node IDs.
        2. For each LogicalNode, resolve the best physical endpoint.
        3. Create the appropriate PhysicalNode (ToolNode or MapNode).
        4. Convert ref-based ``depends_on`` to ID-based ``depends_on``.
        5. Topological sort into execution waves.
        6. Return the complete ExecutionGraph.
        """
        if not workflow.nodes:
            empty_id = self._deterministic_id("empty_graph")
            return ExecutionGraph(graph_id=empty_id, nodes={}, waves=[])

        # Step 1: deterministic ref → id mapping
        ref_to_id: dict[str, str] = {}
        for node in workflow.nodes:
            if node.iterate_over:
                ref_to_id[node.ref] = self._deterministic_id("map", node.op, node.ref)
            else:
                ref_to_id[node.ref] = self._deterministic_id("node", node.op, node.ref)

        # Step 2-3: resolve tools and create physical nodes
        physical_nodes: dict[str, Any] = {}
        for l_node in workflow.nodes:
            dep_ids = [ref_to_id[d] for d in l_node.depends_on if d in ref_to_id]

            try:
                endpoint = await self.resolver.resolve(l_node.op)
            except CapabilityError:
                endpoint = None
            endpoint_url = endpoint.url if endpoint else ""
            tool_name = l_node.op
            http_method = endpoint.http_method if endpoint else "GET"
            cost_est = endpoint.cost_per_call if endpoint and endpoint.cost_per_call is not None else 0.0
            from nexus.config.settings import get_settings as _cg_settings
            _def_lat = _cg_settings().compiler.default_latency_ms
            lat_est = endpoint.latency_p99_ms if endpoint and endpoint.latency_p99_ms is not None else _def_lat

            if l_node.iterate_over:
                p_id = ref_to_id[l_node.ref]
                body_id = self._deterministic_id("body", l_node.op, l_node.ref)
                tool_node = ToolNode(
                    id=body_id,
                    symbolic_ref=l_node.ref,
                    depends_on=dep_ids,
                    capability=l_node.op,
                    tool_name=tool_name,
                    endpoint_url=endpoint_url,
                    http_method=http_method,
                    inputs=dict(l_node.inputs),
                    cost_estimate=cost_est,
                    latency_estimate_ms=lat_est,
                )
                map_node = MapNode(
                    id=p_id,
                    symbolic_ref=f"{l_node.ref}_map",
                    depends_on=dep_ids,
                    iterate_over=l_node.iterate_over,
                    body=tool_node,
                )
                physical_nodes[p_id] = map_node
            else:
                p_id = ref_to_id[l_node.ref]
                tool_node = ToolNode(
                    id=p_id,
                    symbolic_ref=l_node.ref,
                    depends_on=dep_ids,
                    capability=l_node.op,
                    tool_name=tool_name,
                    endpoint_url=endpoint_url,
                    http_method=http_method,
                    inputs=dict(l_node.inputs),
                    cost_estimate=cost_est,
                    latency_estimate_ms=lat_est,
                )
                physical_nodes[p_id] = tool_node

        # Step 4: static dataflow analysis — wire implicit depends_on from placeholders
        self._wire_implicit_dependencies(physical_nodes, ref_to_id)

        # Step 5: topological sort (Kahn's algorithm) → waves
        waves = self._build_waves(physical_nodes)

        graph_id = self._deterministic_id("graph", workflow.version or "1.0", str(sorted(ref_to_id.keys())))
        return ExecutionGraph(
            version="1.0",
            graph_id=graph_id,
            nodes=physical_nodes,
            waves=waves,
        )

    @staticmethod
    def _build_waves(
        nodes: dict[str, Any],
    ) -> list[list[str]]:
        """Pure topological sort using Kahn's algorithm.

        Returns a list of waves, where each wave is a list of node IDs
        that can execute in parallel (no remaining dependencies).
        """
        in_degree: dict[str, int] = {}
        children: dict[str, list[str]] = {}

        for nid, node in nodes.items():
            deps = getattr(node, "depends_on", []) or []
            in_degree[nid] = len(deps)
            for dep in deps:
                children.setdefault(dep, []).append(nid)

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

        processed = sum(len(w) for w in waves)
        if processed < len(nodes):
            raise CompilerError(
                f"Cycle detected: {len(nodes) - processed} nodes unreachable from roots. "
                f"Nodes: {list(nodes.keys())}"
            )

        return waves

    @staticmethod
    def _wire_implicit_dependencies(
        nodes: dict[str, Any],
        ref_to_id: dict[str, str],
    ) -> None:
        """Static dataflow analysis — wire ``depends_on`` from ``${ref.result}`` placeholders.

        Scans every node's inputs for ``${ref.result...}`` patterns and
        automatically adds the referenced refs as dependencies.  The LLM
        may forget to set ``depends_on`` — this catches all cases.
        """
        placeholder_re = re.compile(r"\$\{([a-zA-Z0-9_]+)\.result")

        for _nid, node in nodes.items():
            from nexus.compiler.ir_models import MapNode, ToolNode

            if isinstance(node, MapNode):
                target = node.body
                # MapNode must also depend on its collection source
                if node.iterate_over and node.iterate_over in ref_to_id:
                    coll_id = ref_to_id[node.iterate_over]
                    if coll_id not in node.depends_on:
                        node.depends_on.append(coll_id)
            elif isinstance(node, ToolNode):
                target = node
            else:
                continue

            found: set[str] = set()
            Compiler._scan_for_placeholders(target.inputs, placeholder_re, found)

            existing = set(target.depends_on)
            for ref_name in found:
                if ref_name in ref_to_id:
                    dep_id = ref_to_id[ref_name]
                    if dep_id not in existing:
                        target.depends_on.append(dep_id)
                        existing.add(dep_id)

    @staticmethod
    def _scan_for_placeholders(
        obj: Any,
        regex: re.Pattern,
        found: set[str],
    ) -> None:
        """Recursively search dict/list/str for ``${ref.result...}`` patterns."""
        if isinstance(obj, dict):
            for v in obj.values():
                Compiler._scan_for_placeholders(v, regex, found)
        elif isinstance(obj, list):
            for item in obj:
                Compiler._scan_for_placeholders(item, regex, found)
        elif isinstance(obj, str):
            found.update(regex.findall(obj))
