"""ExecutionGoal — composable goal flags replacing the query-type taxonomy.

Goals model INTENT (what the user wants), not implementation (how many tools
are needed). A request can activate multiple flags — ``{"analysis", "action"}``
for "analyze sales and email the report" — and a deterministic priority
derives the ``primary`` goal used for routing.

Legacy ``QueryType`` values (persisted checkpoints, old state) map through
``from_legacy`` so routing never breaks across versions.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ExecutionGoal(str, Enum):
    """One goal flag. A request may carry several."""

    CONVERSATION = "conversation"
    INFORMATION = "information"
    ANALYSIS = "analysis"
    ACTION = "action"
    WORKFLOW = "workflow"


# Deterministic routing priority (workflow dominates, conversation last).
_GOAL_PRIORITY: tuple[ExecutionGoal, ...] = (
    ExecutionGoal.WORKFLOW,
    ExecutionGoal.ACTION,
    ExecutionGoal.ANALYSIS,
    ExecutionGoal.INFORMATION,
    ExecutionGoal.CONVERSATION,
)

# Legacy QueryType → goal mapping (checkpoint compat). ``None`` = modifier.
_LEGACY_ALIASES: dict[str, ExecutionGoal | None] = {
    "no_tool": ExecutionGoal.CONVERSATION,
    "greeting": ExecutionGoal.CONVERSATION,
    "conversational": ExecutionGoal.CONVERSATION,
    "knowledge_only": ExecutionGoal.INFORMATION,
    "single_tool": ExecutionGoal.ACTION,
    "independent_multi": ExecutionGoal.ACTION,
    "dependent_multi": ExecutionGoal.ACTION,
    "needs_requirements": None,
    "workflow": ExecutionGoal.WORKFLOW,
    "action": ExecutionGoal.ACTION,
    "analysis": ExecutionGoal.ANALYSIS,
    "information": ExecutionGoal.INFORMATION,
    "conversation": ExecutionGoal.CONVERSATION,
}


class ExecutionGoals(BaseModel):
    """Immutable goal set + routing-relevant derivation."""

    model_config = ConfigDict(frozen=True)

    goals: tuple[ExecutionGoal, ...] = Field(
        default_factory=tuple, description="Active goal flags (at least one)"
    )
    needs_requirements: bool = Field(
        default=False,
        description="Modifier: clarification required before planning",
    )

    @property
    def primary(self) -> ExecutionGoal:
        """Deterministic primary goal by fixed priority (never ambiguous)."""
        if not self.goals:
            return ExecutionGoal.CONVERSATION
        for goal in _GOAL_PRIORITY:
            if goal in self.goals:
                return goal
        return ExecutionGoal.CONVERSATION

    @property
    def values(self) -> list[str]:
        return [g.value for g in self.goals]

    @classmethod
    def from_legacy(cls, qtype: str) -> "ExecutionGoals":
        """Map a legacy QueryType value (persisted checkpoints) to goals."""
        goal = _LEGACY_ALIASES.get(qtype, ExecutionGoal.ACTION)
        if goal is None:
            return cls(goals=(ExecutionGoal.ACTION,), needs_requirements=True)
        return cls(goals=(goal,))

    def to_state(self) -> dict[str, object]:
        """State fields for the node output (primary goal + flags + modifier)."""
        return {
            "_query_type": self.primary.value,
            "_goals": self.values,
            "_needs_requirements": self.needs_requirements,
        }

    @classmethod
    def from_values(cls, values: list[str]) -> "ExecutionGoals":
        """Build from raw flag strings (LLM classifier output)."""
        goals: list[ExecutionGoal] = []
        for v in values:
            try:
                goal = ExecutionGoal(v)
            except ValueError:
                continue
            if goal not in goals:
                goals.append(goal)
        return cls(goals=tuple(goals))
