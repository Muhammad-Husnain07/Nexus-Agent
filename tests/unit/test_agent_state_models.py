"""Unit tests for agent state Pydantic models — IntentAnalysis, AnalysisResult, etc."""

from __future__ import annotations

import pytest

from nexus.agent.state import (
    AnalysisResult,
    IntentAnalysis,
    MissingSlot,
    PlanStep,
)


class TestMissingSlot:
    """MissingSlot Pydantic model."""

    def test_minimal(self) -> None:
        slot = MissingSlot(
            name="location",
            description="City name",
            why_needed="required by weather API",
            suggested_question="Which city?",
        )
        assert slot.source == "user"
        assert slot.possible_values is None

    def test_with_possible_values(self) -> None:
        slot = MissingSlot(
            name="city",
            description="Target city",
            why_needed="weather API",
            suggested_question="Which city?",
            possible_values=["NYC", "London", "Tokyo"],
            source="user",
        )
        assert "NYC" in slot.possible_values

    def test_tool_source(self) -> None:
        slot = MissingSlot(
            name="user_id",
            description="Authenticated user ID",
            why_needed="identify user",
            suggested_question="",
            source="context",
        )
        assert slot.source == "context"


class TestIntentAnalysis:
    """IntentAnalysis Pydantic model."""

    def test_minimal(self) -> None:
        analysis = IntentAnalysis(
            primary_goal="send email",
            implied_actions=["compose", "send"],
        )
        assert analysis.confidence == 1.0
        assert analysis.urgency == "normal"
        assert len(analysis.missing_info_slots) == 0

    def test_with_missing_slots(self) -> None:
        slot = MissingSlot(
            name="body",
            description="Email body",
            why_needed="content to send",
            suggested_question="What should the email say?",
        )
        analysis = IntentAnalysis(
            primary_goal="send email",
            missing_info_slots=[slot],
            confidence=0.85,
            urgency="high",
        )
        assert len(analysis.missing_info_slots) == 1
        assert analysis.missing_info_slots[0].name == "body"
        assert analysis.urgency == "high"

    def test_high_urgency(self) -> None:
        analysis = IntentAnalysis(
            primary_goal="delete database",
            urgency="high",
            confidence=0.99,
        )
        assert analysis.urgency == "high"


class TestAnalysisResult:
    """AnalysisResult Pydantic model."""

    def test_success_continue(self) -> None:
        result = AnalysisResult(
            outcome="success",
            next_action="continue",
            reasoning="Step completed as expected",
        )
        assert result.outcome == "success"
        assert result.next_action == "continue"

    def test_failure_revise(self) -> None:
        result = AnalysisResult(
            outcome="failure",
            next_action="revise",
            reasoning="Tool returned unexpected data",
        )
        assert result.next_action == "revise"

    def test_partial_clarify(self) -> None:
        result = AnalysisResult(
            outcome="partial",
            next_action="clarify",
            reasoning="Need more input from user",
        )
        assert result.outcome == "partial"
        assert result.next_action == "clarify"

    def test_finalize(self) -> None:
        result = AnalysisResult(
            outcome="success",
            next_action="finalize",
            reasoning="All steps done",
        )
        assert result.next_action == "finalize"

    def test_escalate_action(self) -> None:
        result = AnalysisResult(
            outcome="failure",
            next_action="escalate",
            reasoning="Cannot handle this error automatically",
        )
        assert result.next_action == "escalate"

    def test_can_have_empty_reasoning(self) -> None:
        result = AnalysisResult(outcome="success", next_action="continue")
        assert result.reasoning == ""


class TestPlanStep:
    """PlanStep Pydantic model."""

    def test_minimal(self) -> None:
        step = PlanStep(id="step_1", description="Do something")
        assert step.status == "pending"
        assert step.tool_name is None
        assert step.inputs is None
        assert step.depends_on == []
        assert step.expected_outcome is None
        assert step.is_destructive is False

    def test_full(self) -> None:
        step = PlanStep(
            id="step_2",
            description="Delete record",
            tool_name="delete_tool",
            inputs={"record_id": "123"},
            status="pending",
            depends_on=["step_1"],
            expected_outcome="Record deleted",
            is_destructive=True,
        )
        assert step.tool_name == "delete_tool"
        assert step.inputs == {"record_id": "123"}
        assert step.is_destructive is True
        assert step.expected_outcome == "Record deleted"

    def test_status_transitions(self) -> None:
        step = PlanStep(id="s1", description="test")
        assert step.status == "pending"
        step.status = "running"
        assert step.status == "running"
        step.status = "done"
        assert step.status == "done"
        step.status = "failed"
        assert step.status == "failed"
        step.status = "skipped"
        assert step.status == "skipped"

    def test_invalid_status(self) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            PlanStep.model_validate(
                {"id": "s1", "description": "test", "status": "invalid"}
            )
