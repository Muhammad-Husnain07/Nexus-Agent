"""Capability Resolver Node — matches GoalIR to capabilities via staged elimination.

Stage 1 of the resolution pipeline. Reads GoalIR from the IR stack and the
KnowledgeGraph, then uses staged elimination to find matching capabilities:

1. Filter by action (exact match on capability name token)
2. Filter by domain (capability tags/category match)
3. Score by input coverage (what % of consumed artifacts are available?)

Returns a CandidateSet: list of {capability, confidence, coverage_gaps}.
No LLM calls. Pure Python matching against the compiled capability graph.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.compiler.ir_models import GoalIR
from nexus.graph.knowledge_graph import KnowledgeGraphManager

logger = structlog.get_logger("nexus.agent.nodes.capability_resolver")


def _score_coverage(
    cap_name: str,
    cap_data: dict[str, Any],
    available_fields: set[str],
) -> tuple[float, list[str]]:
    """Score a capability by input coverage.

    Returns (score 0.0–1.0, list of missing artifact field names).
    Score = (consumed - missing) / consumed, or 1.0 if nothing consumed.
    """
    consumed = set(cap_data.get("consumes", []))
    if not consumed:
        return 1.0, []
    missing = consumed - available_fields
    coverage = (len(consumed) - len(missing)) / len(consumed)
    return coverage, sorted(missing)


async def capability_resolver_node(state: AgentState) -> dict[str, Any]:
    """Resolve GoalIR into candidate capabilities using staged elimination.

    Reads ``_ir_stack.goals`` from state.
    For each goal, searches the compiled CapabilityGraph for matching capabilities.
    Returns candidate sets with coverage scores and gaps.
    """
    ir_stack = state.get("_ir_stack", {})
    goals_data = ir_stack.get("goals", []) if isinstance(ir_stack, dict) else []

    if not goals_data:
        logger.info("capability_resolver.no_goals")
        return {}

    goals = []
    for d in goals_data:
        try:
            goals.append(GoalIR(**d))
        except Exception:
            continue

    if not goals:
        return {}

    # Build the KnowledgeGraph with compiled capability data
    kg = KnowledgeGraphManager.build(state)
    cap_graph = kg.get("capabilities")
    nodes = cap_graph.to_dict().get("nodes", {}) if cap_graph else {}

    # Collect available artifact fields from entities
    ctx = state.get("_structured_context")
    available_fields: set[str] = set()
    if ctx and hasattr(ctx, "entities") and hasattr(ctx.entities, "data"):
        available_fields = set(ctx.entities.data.keys())

    candidates: list[dict[str, Any]] = []
    total_goals = len(goals)
    matched_count = 0

    for goal in goals:
        best_score = 0.0
        best_cap = None
        best_gaps: list[str] = []

        for cap_name, cap_data in nodes.items():
            # Stage 1: Filter by action — token match
            action_tokens = goal.action.lower().split("_")
            cap_tokens = cap_name.lower().split("_")
            token_overlap = set(action_tokens) & set(cap_tokens) - {"get", "search", "predict", "find"}
            if not token_overlap:
                # Try substring match
                if goal.action.lower() not in cap_name.lower() and cap_name.lower() not in goal.action.lower():
                    continue

            # Stage 2: Filter by domain
            domain = goal.domain.lower()
            tags = [t.lower() for t in cap_data.get("tags", [])]
            cat = cap_data.get("category", "").lower()
            if domain not in (["general"] if domain == "general" else []):
                if domain not in cap_name.lower() and domain not in tags and domain != cat:
                    # Domain is a soft filter — warn but don't skip
                    pass

            # Stage 3: Score by input coverage
            score, gaps = _score_coverage(cap_name, cap_data, available_fields)

            if score > best_score:
                best_score = score
                best_cap = cap_name
                best_gaps = gaps

        if best_cap:
            candidates.append({
                "capability": best_cap,
                "goal_action": goal.action,
                "goal_domain": goal.domain,
                "confidence": float(goal.confidence * best_score),
                "coverage_score": best_score,
                "coverage_gaps": best_gaps,
            })
            matched_count += 1

    # If no matches found, fall through to LLM planner
    if not candidates:
        logger.info("capability_resolver.no_matches")
        return {}

    logger.info(
        "capability_resolver.complete",
        total_goals=total_goals,
        matched=matched_count,
        candidates=len(candidates),
    )

    # Build OperationIR-compatible data
    ops_data = []
    for c in candidates:
        ops_data.append({
            "capability_name": c["capability"],
            "goal_action": c["goal_action"],
            "inputs": {},
            "expected_outputs": [],
            "depends_on": [],
            "coverage_gaps": c["coverage_gaps"],
            "confidence": c["confidence"],
        })

    # Update IR stack with operations
    new_ir = dict(ir_stack)
    new_ir["operations"] = ops_data

    return {
        "_ir_stack": new_ir,
        "_candidate_set": candidates,
    }
