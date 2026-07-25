"""Goal Expander Node — expands IntentIR into GoalIR via compiled registry.

Reads IntentIR from the IR stack, looks up CompiledGoalTemplate by trigger_action
in the compiled capability graph, and expands into a list of GoalIR.

No hardcoded expansion logic. All expansion rules come from the compiled registry.
Falls back to simple action-to-goal mapping if no template found.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.compiler.compiled_graph import find_goal_template, get_compiled_graph
from nexus.compiler.ir_models import GoalIR, IntentIR

logger = structlog.get_logger("nexus.agent.nodes.goal_expander")


def _action_to_goal(intent: IntentIR) -> list[GoalIR]:
    """Fallback: derive a single GoalIR from an IntentIR when no template exists.

    Uses the intent's action and domain to create a sensible goal.
    No hardcoded action names — derived from the intent data itself.
    """
    return [
        GoalIR(
            action=intent.action,
            domain=intent.domain,
            required_artifacts=list(intent.entities.keys()),
            produced_artifacts=[],
            confidence=intent.confidence,
        )
    ]


async def goal_expander_node(state: AgentState) -> dict[str, Any]:
    """Expand IntentIR into GoalIR using compiled goal templates.

    Reads `_ir_stack.intents` from state.
    For each intent, looks up the CompiledGoalTemplate by trigger_action.
    Falls back to simple action→goal if no template found.
    Returns updated IR stack with goals populated.
    """
    ir_stack = state.get("_ir_stack", {})
    intents_data = ir_stack.get("intents", []) if isinstance(ir_stack, dict) else []

    if not intents_data:
        logger.info("goal_expander.no_intents")
        return {}

    # Reconstruct IntentIR objects from stack data
    intents = []
    for d in intents_data:
        try:
            intents.append(IntentIR(**d))
        except Exception:
            continue

    if not intents:
        return {}

    all_goals: list[GoalIR] = []
    total = len(intents)
    expanded_count = 0

    for intent in intents:
        # Try compiled registry first
        tmpl = find_goal_template(intent.action)
        if tmpl:
            capability_chain = tmpl.get("capability_chain", [])
            for cap_name in capability_chain:
                goal = GoalIR(
                    action=cap_name,
                    domain=intent.domain,
                    required_artifacts=list(intent.entities.keys()),
                    produced_artifacts=[],
                    confidence=intent.confidence,
                )
                all_goals.append(goal)
                expanded_count += 1
        else:
            # Fallback: derive from intent
            goals = _action_to_goal(intent)
            all_goals.extend(goals)

    logger.info(
        "goal_expander.complete",
        total_intents=total,
        total_goals=len(all_goals),
        expanded_from_registry=expanded_count,
    )

    # Build updated IR stack
    new_ir = dict(ir_stack)
    new_ir["goals"] = [g.model_dump() for g in all_goals]

    return {
        "_ir_stack": new_ir,
    }
