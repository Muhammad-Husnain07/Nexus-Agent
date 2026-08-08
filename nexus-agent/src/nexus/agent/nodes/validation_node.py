"""Validation node — pure Python validation for the 13-node compiler pipeline.

Validates that:
1. A ``_logical_workflow`` exists and has at least one node.
2. The optimized graph (``_execution_graph``) is structurally sound.
3. The budget estimate (``_within_budget``) allows execution.

No LLM calls. Fast (~0ms).
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.validation")


async def validation_node(state: AgentState) -> dict[str, Any]:
    """Validate the compiler pipeline output before execution.

    Checks:
    - ``_logical_workflow`` exists and has nodes.
    - ``_optimized_graph`` (or ``_execution_graph``) is valid.
    - Budget/latency within acceptable thresholds.

    Returns:
        - ``_validation_result``: the full validation result dict.
        - ``_ready_to_plan``: True if execution should proceed (renamed for routing compat).
        - ``_needs_clarification``: True if clarification is needed.
    """
    workflow = state.get("_logical_workflow")
    graph = state.get("_execution_graph")
    within_budget = state.get("_within_budget", True)
    warnings = state.get("_estimate_warnings", [])

    missing: list[str] = []
    reason = ""

    # Stage 1: Workflow exists
    if not workflow:
        missing.append("workflow")
        reason = "What would you like me to help with?"
    else:
        nodes = workflow.get("nodes", []) if isinstance(workflow, dict) else []
        if not nodes:
            missing.append("operations")
            reason = "I need more specific instructions to build a plan."

    # Stage 2: Graph exists
    if not missing and not graph:
        missing.append("execution_graph")
        reason = "Could not compile a valid execution plan."

    # Stage 3: Budget check
    if not missing and not within_budget:
        warnings_str = "; ".join(warnings[:3])
        logger.warning("validation_node.budget_exceeded", warnings=warnings_str)
        missing.append("budget")
        reason = f"Budget constraints exceeded: {warnings_str}"

    ready = len(missing) == 0
    needs_clarification = not ready

    if needs_clarification:
        logger.info(
            "validation_node.needs_clarification",
            missing=missing,
            reason=reason,
        )
    else:
        logger.info(
            "validation_node.ready",
            graph_nodes=len(graph.get("nodes", {})) if isinstance(graph, dict) else 0,
        )

    return {
        "_validation_result": {
            "ready": ready,
            "missing": missing,
            "reason": reason,
        },
        "_ready_to_plan": ready,
        "_needs_clarification": needs_clarification,
    }


def validation_result_as_string(result: dict[str, Any]) -> str:
    """Convert a validation result into a human-readable clarification question."""
    missing = result.get("missing", [])
    reason = result.get("reason", "")
    if not missing or not reason:
        return ""
    return reason
