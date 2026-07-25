"""Dependency Resolver Node — resolves missing inputs via compiled capability graph.

Stage 2 of the resolution pipeline. Reads Candidate Sets from the IR stack.
For each candidate with coverage_gaps, queries the compiled CapabilityGraph
for a producer capability that can satisfy the missing input.

Appends new OperationIR tasks for any prerequisite capabilities found.
No LLM calls. Pure BFS on the compiled graph adjacency.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.compiler.ir_models import OperationIR
from nexus.graph.knowledge_graph import KnowledgeGraphManager

logger = structlog.get_logger("nexus.agent.nodes.dependency_resolver")


async def dependency_resolver_node(state: AgentState) -> dict[str, Any]:
    """Resolve missing inputs by finding producer capabilities in the compiled graph.

    Reads ``_ir_stack.operations`` from state.
    For each operation with coverage_gaps, searches the compiled CapabilityGraph
    adjacency for a capability whose ``produces`` includes the missing artifact.
    Appends new OperationIR tasks for any prerequisite capabilities.
    """
    ir_stack = state.get("_ir_stack", {})
    ops_data = ir_stack.get("operations", []) if isinstance(ir_stack, dict) else []

    if not ops_data:
        logger.info("dependency_resolver.no_operations")
        return {}

    # Load compiled capability graph
    kg = KnowledgeGraphManager.build(state)
    cap_graph = kg.get("capabilities")
    nodes = cap_graph.to_dict().get("nodes", {}) if cap_graph else {}
    adjacency = cap_graph.to_dict().get("adjacency", {}) if cap_graph else {}

    new_ops = list(ops_data)
    resolved_count = 0
    prereq_count = 0

    for op in new_ops:
        gaps = op.get("coverage_gaps", [])
        if not gaps:
            continue

        resolved_gaps: list[str] = []
        for gap in list(gaps):
            # Find a capability that produces the missing artifact
            for cap_name, cap_data in nodes.items():
                produces = cap_data.get("produces", [])
                if gap in produces:
                    # Check if this producer isn't already in the plan
                    existing = [o for o in new_ops if o.get("capability_name") == cap_name]
                    if not existing:
                        prereq_op = {
                            "capability_name": cap_name,
                            "goal_action": cap_name,
                            "inputs": {},
                            "expected_outputs": [gap],
                            "depends_on": [],
                            "coverage_gaps": [],
                            "confidence": 0.8,
                        }
                        new_ops.append(prereq_op)
                        prereq_count += 1
                    resolved_gaps.append(gap)
                    break

        # Remove resolved gaps
        for g in resolved_gaps:
            gaps.remove(g)
        if not gaps:
            resolved_count += 1

    logger.info(
        "dependency_resolver.complete",
        total_ops=len(ops_data),
        resolved=resolved_count,
        prereqs_added=prereq_count,
    )

    # Build proper OperationIR objects for the updated IR stack
    operations = []
    seen = set()
    for od in new_ops:
        cap_name = od.get("capability_name", "")
        if cap_name in seen:
            continue
        seen.add(cap_name)
        try:
            op = OperationIR(
                capability_name=cap_name,
                tool_name="",
                inputs=od.get("inputs", {}),
                expected_outputs=od.get("expected_outputs", []),
                depends_on=od.get("depends_on", []),
            )
            operations.append(op.model_dump())
        except Exception:
            continue

    new_ir = dict(ir_stack)
    new_ir["operations"] = operations

    return {
        "_ir_stack": new_ir,
    }
