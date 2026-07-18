"""Unit tests for the feedback_interrupt module."""

from __future__ import annotations

from unittest.mock import patch

from nexus.agent.feedback_interrupt import interrupt_for_feedback


class TestInterruptForFeedback:
    """feedback_interrupt.interrupt_for_feedback — delegates to interrupt()."""

    async def test_approve(self) -> None:
        with patch("nexus.agent.feedback_interrupt.interrupt", return_value={"action": "approve"}):
            result = interrupt_for_feedback({"type": "preview", "preview": "test"})
        assert result["action"] == "approve"
        assert result["feedback"] is None

    async def test_reject(self) -> None:
        with patch(
            "nexus.agent.feedback_interrupt.interrupt",
            return_value={"action": "reject", "feedback": "Not good"},
        ):
            result = interrupt_for_feedback({"type": "preview", "preview": "test"})
        assert result["action"] == "reject"
        assert result["feedback"] == "Not good"

    async def test_edit_with_modifications(self) -> None:
        with patch(
            "nexus.agent.feedback_interrupt.interrupt",
            return_value={
                "action": "edit",
                "modifications": {"text": "edited"},
                "feedback": "Change text",
            },
        ):
            result = interrupt_for_feedback({"type": "preview", "preview": "test"})
        assert result["action"] == "edit"
        assert result["modifications"] == {"text": "edited"}
        assert result["feedback"] == "Change text"

    async def test_defaults_to_approve(self) -> None:
        with patch("nexus.agent.feedback_interrupt.interrupt", return_value={"unknown": True}):
            result = interrupt_for_feedback({"type": "preview", "preview": "test"})
        assert result["action"] == "approve"
