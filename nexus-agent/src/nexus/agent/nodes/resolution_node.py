"""Resolution Node — resolves user intent into a capability chain via graph search.

Stage 1 of the 3-stage planner pipeline.

Uses A* search over the Capability Registry's capability graph to find
all valid paths from user-provided artifacts to the goal artifact.
Returns a resolved capability chain without selecting specific tools.

Pure Python graph algorithm — no LLM calls.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState

logger = structlog.get_logger("nexus.agent.nodes.resolution")


def _astar_search(
    capabilities: dict[str, Any],
    start_artifacts: set[str],
    goal_artifact: str,
    max_depth: int = 10,
) -> list[list[str]]:
    """A* search over the capability graph.

    Each capability has ``consumes`` and ``produces`` artifact lists.
    The graph edges are: capability A can feed capability B if
    A produces an artifact that B consumes.

    Args:
        capabilities: Dict of capability name → data (with consumes/produces).
        start_artifacts: Artifact field names the user has already provided.
        goal_artifact: The target artifact field name to produce.
        max_depth: Maximum chain length to prevent infinite search.

    Returns:
        List of capability name chains (paths) that satisfy the goal.
    """
    paths: list[list[str]] = []

    def _heuristic(cap_name: str) -> float:
        """Estimate remaining cost: fewer remaining steps = lower cost."""
        cap = capabilities.get(cap_name)
        if not cap:
            return max_depth
        if goal_artifact in cap.get("produces", []):
            return 0.0
        return 1.0

    # BFS with heuristic pruning
    from collections import deque
    queue: deque[tuple[list[str], set[str], float]] = deque()
    queue.append(([], set(start_artifacts), 0.0))

    while queue and len(paths) < 5:
        chain, available, cost = queue.popleft()

        if len(chain) >= max_depth:
            continue

        # Find all capabilities that can execute with available artifacts
        for cap_name, cap_data in capabilities.items():
            if cap_name in chain:
                continue

            consumes = set(cap_data.get("consumes", []))
            # A capability is executable if it has no required consumes, or all are available
            if consumes and not (consumes & available):
                continue

            new_available = available | set(cap_data.get("produces", []))
            new_chain = chain + [cap_name]

            if goal_artifact in cap_data.get("produces", []):
                paths.append(new_chain)
                continue

            h = _heuristic(cap_name)
            queue.append((new_chain, new_available, cost + 1.0 + h))

    return paths


async def resolution_node(state: AgentState) -> dict[str, Any]:
    """Resolve user intent into a capability chain using graph search.

    Pure Python A* search over the capability registry graph.
    No LLM calls. Returns resolved capability chain or empty if no path found.

    The existing PlannerNode acts as fallback when resolution fails.
    """
    intents = []
    ctx = state.get("_structured_context")
    if ctx and hasattr(ctx, "intent") and ctx.intent:
        if isinstance(ctx.intent, list):
            intents = ctx.intent
        else:
            intents = [ctx.intent]

    if not intents:
        # Fallback: try flat fields
        intent_analysis = state.get("intent_analysis")
        if isinstance(intent_analysis, dict):
            goal = intent_analysis.get("primary_goal", "")
            if goal:
                intents = [goal]

    if not intents:
        logger.info("resolution_node.no_intent")
        return {}  # Fall through to PlannerNode

    # Get capability registry
    try:
        from nexus.agent.registry.capability_registry import get_capability_registry
        cap_reg = get_capability_registry()
        capabilities = {c.name: {
            "name": c.name,
            "consumes": c.consumes,
            "produces": c.produces,
            "tool_names": c.tool_names,
        } for c in cap_reg.get_capabilities()}
    except Exception:
        logger.warning("resolution_node.registry_unavailable")
        return {}

    if not capabilities:
        logger.info("resolution_node.no_capabilities")
        return {}

    # Extract available artifacts from StructuredContext entities
    available_artifacts: set[str] = set()
    if ctx and hasattr(ctx, "entities") and hasattr(ctx.entities, "data"):
        available_artifacts = set(ctx.entities.data.keys())

    # Search for each intent as a goal artifact
    all_chains: list[list[str]] = []
    for intent in intents:
        # Use intent as the goal artifact name to search for
        paths = _astar_search(capabilities, available_artifacts, intent)
        all_chains.extend(paths)

    if not all_chains:
        logger.info("resolution_node.no_chain_found", intents=intents)
        return {}  # Fall through to PlannerNode

    # Pick the shortest chain
    best_chain = min(all_chains, key=len)

    logger.info(
        "resolution_node.chain_found",
        chain=best_chain,
        length=len(best_chain),
    )

    return {
        "_resolution_chain": best_chain,
        "_resolved_artifacts": list(available_artifacts),
    }
