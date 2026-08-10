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
from nexus.capabilities.resolver import DynamicCapabilityResolver
from nexus.compiler.resolver import CapabilityError


class CompilerError(Exception):
    """Raised when the Compiler cannot resolve a logical operation."""


class Compiler:
    """Deterministic compiler translating LogicalWorkflow → ExecutionGraph.

    Usage::

        resolver = DynamicCapabilityResolver(db_session)
        compiler = Compiler(resolver)
        graph = await compiler.compile(workflow)

    Pure: all ID generation uses SHA256 hashing, never ``uuid.uuid4()``.
    """

    def __init__(self, resolver: DynamicCapabilityResolver) -> None:
        self.resolver = resolver

    def _deterministic_id(self, *parts: str, length: int = 12) -> str:
        """Pure: generate a deterministic ID from any number of string parts.

        Same inputs always produce the same ID. No I/O, no datetime, no random.
        """
        raw = "::".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:length]

    async def _synthesize_resolve_producers(
        self,
        workflow: LogicalWorkflow,
        resolver_context: Any | None = None,
    ) -> LogicalWorkflow:
        """Deterministic chain insertion for ``RESOLVE(...)`` expressions.

        The planner may emit ``RESOLVE("capability", "input_key", "value")``
        instead of ``${ref.result.field}`` placeholders to declare a
        producer chain. This pre-pass synthesizes the producer LogicalNode
        (metadata-driven via the resolver + registry), rewrites the
        consumer's input to the corresponding ``${producer_ref.result.<a>}``
        placeholder, and wires the dependency. The frozen IR is REBUILT
        (never mutated).

        FAIL-CLOSED (invariant I1): a chain expression that cannot be
        synthesized — unknown capability, no resolvable endpoint, missing
        producer input contract, or an unsupported chain form — raises
        ``CompilerError`` so the expression NEVER crosses into execution as
        a literal string. The compiler node routes the failure back to the
        planner (bounded replan), never to the executor.
        """
        from nexus.agent.nodes.plan_validator_node import _is_chain_expression
        from nexus.artifacts.normalizer import strip_normalization_state  # noqa: F401
        from nexus.context.global_context import get_global_context

        resolve_re = re.compile(
            r'RESOLVE\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)'
        )
        synthesized: list[LogicalNode] = []
        rewritten: dict[str, dict[str, Any]] = {}
        extra_deps: dict[str, list[str]] = {}
        producer_by_ref: dict[str, str] = {}

        index = {}
        try:
            index = getattr(get_global_context(), "capability_index", None) or {}
        except Exception:
            index = {}

        existing_refs = {n.ref for n in workflow.nodes}

        def _producer_meta(name: str) -> dict:
            meta = index.get(name) or {}
            return meta if isinstance(meta, dict) else {}

        for node in workflow.nodes:
            if not node.inputs:
                continue
            new_inputs = dict(node.inputs)
            changed = False
            for key, value in list(new_inputs.items()):
                if not (isinstance(value, str) and _is_chain_expression(value)):
                    continue
                match = resolve_re.search(value)
                if not match:
                    # Unsupported chain form (e.g. the legacy "{{ref}}"
                    # variant) — never a literal passthrough (I1).
                    raise CompilerError(
                        f"cannot compile unsupported chain expression {value!r} "
                        f"in input '{key}' of node '{node.ref}' — resolve it "
                        "before execution"
                    )
                producer_op, producer_key, producer_value = (
                    match.group(1), match.group(2), match.group(3),
                )
                meta = _producer_meta(producer_op)
                if not meta:
                    raise CompilerError(
                        f"RESOLVE(...) references unknown capability "
                        f"'{producer_op}' in input '{key}' of node "
                        f"'{node.ref}' — cannot synthesize producer"
                    )
                try:
                    candidates = await self.resolver.resolve(
                        producer_op, context=resolver_context
                    )
                except Exception as exc:
                    raise CompilerError(
                        f"RESOLVE(...) producer resolution failed for "
                        f"'{producer_op}' in input '{key}' of node "
                        f"'{node.ref}': {exc}"
                    ) from exc
                if not candidates:
                    raise CompilerError(
                        f"RESOLVE(...) capability '{producer_op}' has no "
                        f"resolvable endpoint — cannot synthesize producer "
                        f"for input '{key}' of node '{node.ref}'"
                    )
                # Producer input mapping: the expression's key if the
                # producer's schema declares it, else its first required
                # input (metadata-driven — mirrors the workflow engine).
                schema = meta.get("input_schema") or {}
                props = schema.get("properties") if isinstance(schema, dict) else {}
                producer_input: dict[str, Any] = {}
                if isinstance(props, dict) and producer_key in props:
                    producer_input[producer_key] = producer_value
                else:
                    required = meta.get("input_required") or []
                    if required:
                        producer_input[str(required[0])] = producer_value
                    else:
                        raise CompilerError(
                            f"RESOLVE(...) producer '{producer_op}' declares "
                            f"no input key contract — cannot synthesize "
                            f"producer for input '{key}' of node '{node.ref}'"
                        )
                producer_ref = f"{node.ref}_producer_{key}"
                if producer_ref in existing_refs:
                    producer_ref = f"{node.ref}_producer_{key}_{len(synthesized)}"
                producer_by_ref[producer_ref] = producer_op
                synthesized.append(LogicalNode(
                    op=producer_op,
                    ref=producer_ref,
                    inputs=producer_input,
                    depends_on=[],
                ))
                # Consumer input rewrite: the consumed artifact ← the
                # producer's produces list (the key itself first, else the
                # first produced artifact).
                produces = meta.get("produces") or []
                field = key if key in produces else (produces[0] if produces else key)
                new_inputs[key] = f"${{{producer_ref}.result.{field}}}"
                extra_deps.setdefault(node.ref, []).append(producer_ref)
                changed = True
            if changed:
                rewritten[node.ref] = new_inputs

        if not synthesized:
            return workflow

        final_nodes = []
        for node in workflow.nodes:
            final_nodes.append(node)
            if node.ref in rewritten:
                final_nodes[-1] = LogicalNode(
                    op=node.op,
                    ref=node.ref,
                    inputs=rewritten[node.ref],
                    depends_on=list(node.depends_on) + extra_deps.get(node.ref, []),
                    condition=node.condition,
                    branch_true=node.branch_true,
                    branch_false=node.branch_false,
                    iterate_over=node.iterate_over,
                    domain=node.domain,
                    action=node.action,
                )
        final_nodes.extend(synthesized)
        return LogicalWorkflow(
            version=workflow.version,
            nodes=final_nodes,
            collections=workflow.collections,
        )


    async def compile(
        self,
        workflow: LogicalWorkflow,
        resolver_context: Any | None = None,
    ) -> ExecutionGraph:
        """Translate a LogicalWorkflow into a complete ExecutionGraph.

        Args:
            workflow: The logical workflow to compile.
            resolver_context: Optional ``ResolverContext`` (permissions,
                tier, preferred version/environment) passed to capability
                resolution for identity-aware scoring.

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

        # Step 0: synthesize producers for declarative chain expressions —
        # ``RESOLVE("capability", "input_key", "value")`` input values are
        # the planner's declared producer intent: a producer node is
        # synthesized (metadata-driven via the resolver), the consumer's
        # input is rewritten to a ``${producer_ref.result.<artifact>}``
        # placeholder, and the dependency is wired. Fully deterministic —
        # never a guessed literal. The frozen IR is REBUILT, never mutated.
        workflow = await self._synthesize_resolve_producers(workflow, resolver_context)

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

            # Conditional gate: no tool resolution — the node routes
            # execution based on ``condition`` against accumulated results.
            if l_node.condition and (l_node.branch_true or l_node.branch_false):
                p_id = ref_to_id.get(l_node.ref) or self._deterministic_id(
                    "cond", l_node.op, l_node.ref
                )
                ref_to_id[l_node.ref] = p_id
                physical_nodes[p_id] = ConditionalNode(
                    id=p_id,
                    symbolic_ref=l_node.ref,
                    depends_on=dep_ids,
                    condition=l_node.condition,
                    branch_true=[ref_to_id[b] for b in l_node.branch_true if b in ref_to_id],
                    branch_false=[ref_to_id[b] for b in l_node.branch_false if b in ref_to_id],
                )
                continue

            # Normalize LLM input wrappers: some models emit
            # ``{"args": {...}}`` / ``{"parameters": {...}}`` instead of a
            # flat inputs dict. Unwrap generically — no tool-specific logic.
            node_inputs = _unwrap_input_wrapper(l_node.inputs)

            try:
                candidates = await self.resolver.resolve(l_node.op, context=resolver_context)
            except CapabilityError:
                candidates = []
            best = candidates[0] if candidates else None
            endpoint_url = best.url if best else ""
            tool_name = l_node.op
            http_method = best.http_method if best else "GET"
            cost_est = best.cost_per_call if best and best.cost_per_call is not None else 0.0
            from nexus.config.settings import get_settings as _cg_settings
            _def_lat = _cg_settings().compiler.default_latency_ms
            lat_est = best.latency_p99_ms if best and best.latency_p99_ms is not None else _def_lat
            candidate_list = [c.model_dump() for c in candidates] if candidates else []

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
                    inputs=dict(node_inputs),
                    cost_estimate=cost_est,
                    latency_estimate_ms=lat_est,
                    candidate_endpoints=candidate_list,
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
                    inputs=dict(node_inputs),
                    cost_estimate=cost_est,
                    latency_estimate_ms=lat_est,
                    candidate_endpoints=candidate_list,
                )
                physical_nodes[p_id] = tool_node

        # Step 4: static dataflow analysis — wire implicit depends_on from placeholders
        self._wire_implicit_dependencies(physical_nodes, ref_to_id)

        # Step 4b: branch nodes depend on their conditional gate — a branch
        # must never execute before the gate has evaluated its condition.
        for node in physical_nodes.values():
            if not isinstance(node, ConditionalNode):
                continue
            for branch_id in node.branch_true + node.branch_false:
                branch = physical_nodes.get(branch_id)
                if branch is not None and node.id not in branch.depends_on:
                    branch.depends_on = list(branch.depends_on) + [node.id]

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


def _unwrap_input_wrapper(inputs: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM input wrappers into a flat inputs dict.

    Some models emit ``{"args": {...}}`` / ``{"parameters": {...}}`` /
    ``{"params": {...}}`` instead of a flat inputs dict. Unwrapping is
    purely structural (single-key wrapper whose value is a dict) — it
    applies to any tool/capability with no tool-specific logic.

    Args:
        inputs: The raw inputs dict from a LogicalNode.

    Returns:
        The unwrapped flat inputs dict (or the original if no wrapper).
    """
    if not isinstance(inputs, dict) or len(inputs) != 1:
        return dict(inputs)
    wrapper_key, wrapper_val = next(iter(inputs.items()))
    if wrapper_key in ("args", "arguments", "parameters", "params", "input") and isinstance(wrapper_val, dict):
        return dict(wrapper_val)
    return dict(inputs)
