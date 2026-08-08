"""Tests for ExecutionGoal flags (Phase 2) — composable goals, primary
derivation, legacy QueryType normalization."""

from __future__ import annotations

from nexus.agent.goals import ExecutionGoal, ExecutionGoals


def test_primary_priority_deterministic():
    """Composable flags derive ONE primary goal by fixed priority."""
    assert ExecutionGoals(goals=(ExecutionGoal.ANALYSIS, ExecutionGoal.ACTION)).primary == ExecutionGoal.ACTION
    assert ExecutionGoals(goals=(ExecutionGoal.ACTION, ExecutionGoal.WORKFLOW)).primary == ExecutionGoal.WORKFLOW
    assert ExecutionGoals(goals=(ExecutionGoal.CONVERSATION, ExecutionGoal.INFORMATION)).primary == ExecutionGoal.INFORMATION
    assert ExecutionGoals(goals=(ExecutionGoal.CONVERSATION,)).primary == ExecutionGoal.CONVERSATION
    assert ExecutionGoals(goals=tuple()).primary == ExecutionGoal.CONVERSATION


def test_legacy_alias_map():
    """Persisted QueryType values normalize to goals — checkpoints never break."""
    assert ExecutionGoals.from_legacy("single_tool").primary == ExecutionGoal.ACTION
    assert ExecutionGoals.from_legacy("independent_multi").primary == ExecutionGoal.ACTION
    assert ExecutionGoals.from_legacy("dependent_multi").primary == ExecutionGoal.ACTION
    assert ExecutionGoals.from_legacy("knowledge_only").primary == ExecutionGoal.INFORMATION
    assert ExecutionGoals.from_legacy("no_tool").primary == ExecutionGoal.CONVERSATION
    assert ExecutionGoals.from_legacy("conversational").primary == ExecutionGoal.CONVERSATION
    assert ExecutionGoals.from_legacy("workflow").primary == ExecutionGoal.WORKFLOW
    # New-style values pass through unchanged.
    assert ExecutionGoals.from_legacy("analysis").primary == ExecutionGoal.ANALYSIS


def test_legacy_needs_requirements_becomes_modifier():
    goals = ExecutionGoals.from_legacy("needs_requirements")
    assert goals.needs_requirements is True
    assert goals.primary == ExecutionGoal.ACTION


def test_from_values_dedupes_and_skips_unknown():
    goals = ExecutionGoals.from_values(["action", "action", "analysis", "nonsense"])
    assert goals.values == ["action", "analysis"]
    assert ExecutionGoals.from_values([]).goals == ()


def test_to_state_shape():
    goals = ExecutionGoals(goals=(ExecutionGoal.ANALYSIS, ExecutionGoal.ACTION), needs_requirements=False)
    state = goals.to_state()
    assert state["_query_type"] == "action"
    assert state["_goals"] == ["analysis", "action"]
    assert state["_needs_requirements"] is False


def test_goals_frozen():
    goals = ExecutionGoals(goals=(ExecutionGoal.ACTION,))
    try:
        goals.goals = (ExecutionGoal.WORKFLOW,)  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except Exception:
        pass
