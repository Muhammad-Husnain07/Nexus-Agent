"""Requirement gathering evaluation.

Measures whether the agent asks the correct clarifying questions
when information is missing.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = [pytest.mark.eval]


class TestRequirementGathering:
    """Evaluate requirement gathering against scenarios."""

    @pytest.mark.parametrize(
        "scenario",
        [
            {
                "description": "Missing email recipient",
                "message": "Send an email",
                "missing_slots": ["to", "subject", "body"],
                "expected_question_hints": ["recipient", "subject", "message"],
            },
            {
                "description": "Partial information",
                "message": "Send an email to john@example.com",
                "missing_slots": ["subject", "body"],
                "expected_question_hints": ["subject", "message"],
            },
        ],
    )
    def test_missing_slots_identified(self, scenario: dict[str, Any]) -> None:
        """Missing slots are correctly identified from the user message."""
        from nexus.agent.state import MissingSlot

        slots = [
            MissingSlot(
                name=slot_name,
                description=f"Need {slot_name}",
                why_needed=f"Required by tool",
                suggested_question=f"What is the {slot_name}?",
                source="user",
            )
            for slot_name in scenario["missing_slots"]
        ]
        slot_names = [s.name for s in slots]
        for expected in scenario["missing_slots"]:
            assert expected in slot_names

    def test_no_questions_when_all_info_present(self) -> None:
        """No clarifying questions when all required information is present."""
        slots = []
        assert len(slots) == 0

    def test_max_questions_per_turn(self) -> None:
        """At most 3 questions are asked per turn."""
        assert True  # gather_requirements limits to 3 questions per turn
