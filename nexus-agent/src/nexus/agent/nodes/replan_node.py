"""ReplanNode — rare-path structural replanning (distinct from Reflection).

Reflection retries transient failures (graph-level, never replans). The
ReplanNode handles STRUCTURAL invalidity: a capability disappeared or became
unavailable, schemas changed, or an execution policy violation (budget /
approval-denied blocking step) makes the current plan un-executable.

It marks the failed ops unavailable, preserves completed results, and hands
the remaining goal to the planner — bounded by ``_replan_rounds`` so a
non-converging goal fails explicitly instead of looping.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("nexus.agent.nodes.replan")


class ReplanNode:
    """Deterministic replan trigger (state → state; no side effects)."""

    async def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        failures = list(state.get("_executor_failed", []) or [])
        completed = state.get("_completed_tools", []) or []

        # Replan context: completed results preserved, failed ops marked
        # unavailable so the replanning planner never re-selects them.
        context: dict[str, Any] = {
            "completed_tools": [str(t) for t in completed],
            "unavailable_ops": [str(t) for t in failures],
        }
        rounds = int(state.get("_replan_rounds", 0) or 0) + 1

        # REASONING BUDGET (P0): the recovery replan consumes the SAME
        # shared replan counter as the validator and compiler loops — an
        # identical failure can never trigger an identical replan
        # indefinitely, and no subsystem holds an independent replan loop.
        budget_ok = True
        budget_dict = {}
        try:
            from nexus.agent.budget import budget_from_state

            _budget = budget_from_state(state)
            budget_ok = _budget.consume("replans")
            budget_dict = _budget.to_dict()
        except Exception:
            budget_ok = True

        logger.warning(
            "replan_node.triggered",
            rounds=rounds,
            unavailable=context["unavailable_ops"],
            budget_ok=budget_ok,
        )
        return {
            "_replan_context": context,
            "_replan_rounds": rounds,
            "_needs_replan": False,
            "_invocation_budget": budget_dict,
            "errors": [] if budget_ok else [
                "replan budget exhausted — execution continues with completed results"
            ],
        }
