"""Unit tests for the agent error hierarchy."""

from __future__ import annotations

import pytest

from nexus.agent.errors import (
    AgentError,
    ApprovalRejected,
    ContextWindowExceededError,
    MaxIterationsError,
    PlanningError,
    ToolExecutionError,
)


class TestAgentErrors:
    """Verify all custom errors are instanceof AgentError."""

    @pytest.mark.parametrize(
        ("exc_cls", "msg"),
        [
            (PlanningError, "plan failed"),
            (ToolExecutionError, "execution error"),
            (MaxIterationsError, "max iterations exceeded"),
            (ContextWindowExceededError, "context window full"),
            (ApprovalRejected, "user rejected"),
        ],
    )
    def test_is_agent_error(self, exc_cls: type[AgentError], msg: str) -> None:
        inst = exc_cls(msg)
        assert isinstance(inst, AgentError)
        assert str(inst) == msg

    def test_base_error_works(self) -> None:
        inst = AgentError("generic agent error")
        assert isinstance(inst, Exception)
        assert str(inst) == "generic agent error"

    def test_catch_base_catches_all(self) -> None:
        errors: list[AgentError] = [
            PlanningError("a"),
            ToolExecutionError("b"),
            MaxIterationsError("c"),
            ContextWindowExceededError("d"),
            ApprovalRejected("e"),
        ]
        for err in errors:
            try:
                raise err
            except AgentError:
                pass
            else:
                pytest.fail(f"{type(err).__name__} not caught by AgentError")
