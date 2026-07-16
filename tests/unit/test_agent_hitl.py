"""Unit tests for the hitl module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nexus.agent.hitl import build_approval_payload, interrupt_for_approval, requires_approval
from nexus.config.settings import AgentSettings


class TestRequiresApproval:
    """hitl.requires_approval — checks all conditions."""

    def _make_tool(
        self, name: str = "test_tool", requires_approval: bool = False, risk_level: str = "low"
    ) -> MagicMock:
        tool = MagicMock()
        tool.name = name
        tool.requires_approval = requires_approval
        tool.risk_level = risk_level
        return tool

    def test_requires_approval_flag(self) -> None:
        tool = self._make_tool(requires_approval=True)
        assert requires_approval(tool, settings=AgentSettings(hitl_default=False))

    def test_requires_approval_risk_medium(self) -> None:
        tool = self._make_tool(risk_level="medium")
        assert requires_approval(tool, settings=AgentSettings(hitl_default=False))

    def test_requires_approval_risk_high(self) -> None:
        tool = self._make_tool(risk_level="high")
        assert requires_approval(tool, settings=AgentSettings(hitl_default=False))

    def test_requires_approval_destructive_step(self) -> None:
        tool = self._make_tool()
        assert requires_approval(
            tool, plan_step={"is_destructive": True}, settings=AgentSettings(hitl_default=False)
        )

    def test_requires_approval_hitl_default(self) -> None:
        tool = self._make_tool()
        assert requires_approval(tool, settings=AgentSettings(hitl_default=True))

    def test_requires_approval_pattern_match(self) -> None:
        tool = self._make_tool(name="delete_staging")
        assert requires_approval(
            tool,
            settings=AgentSettings(hitl_default=False, hitl_tool_patterns=["delete_.*"]),
        )

    def test_no_approval_needed(self) -> None:
        tool = self._make_tool()
        assert not requires_approval(tool, settings=AgentSettings(hitl_default=False))

    def test_default_settings_require_approval(self) -> None:
        """Default AgentSettings has hitl_default=True."""
        tool = self._make_tool()
        assert requires_approval(tool, settings=AgentSettings())


class TestBuildApprovalPayload:
    """hitl.build_approval_payload — payload shape."""

    def _make_tool(self, name: str = "test_tool", risk_level: str = "low") -> MagicMock:
        tool = MagicMock()
        tool.name = name
        tool.risk_level = risk_level
        return tool

    def test_minimal_payload(self) -> None:
        tool = self._make_tool()
        payload = build_approval_payload(tool, func_args={"arg1": "val1"})
        assert payload["kind"] == "tool_approval"
        assert payload["tool_call"]["name"] == "test_tool"
        assert payload["tool_call"]["inputs"] == {"arg1": "val1"}
        assert payload["question"] == "Approve execution of 'test_tool'?"
        assert payload["risk_level"] == "low"

    def test_payload_with_step(self) -> None:
        tool = self._make_tool()
        payload = build_approval_payload(
            tool,
            plan_step={"id": "step_1", "description": "Do something", "is_destructive": True},
            func_args={},
        )
        assert payload["step"]["id"] == "step_1"
        assert payload["step"]["description"] == "Do something"
        assert payload["step"]["is_destructive"] is True


class TestInterruptForApproval:
    """hitl.interrupt_for_approval — delegates to interrupt()."""

    async def test_approve_decision(self) -> None:
        with patch("nexus.agent.hitl.interrupt", return_value={"action": "approve"}):
            decision = interrupt_for_approval({"dummy": True})
        assert decision["action"] == "approve"
        assert decision["edited_inputs"] is None

    async def test_reject_decision(self) -> None:
        return_value = {"action": "reject", "comment": "Not now"}
        with patch("nexus.agent.hitl.interrupt", return_value=return_value):
            decision = interrupt_for_approval({"dummy": True})
        assert decision["action"] == "reject"
        assert decision["comment"] == "Not now"

    async def test_edit_decision(self) -> None:
        return_value = {
            "action": "edit",
            "edited_inputs": {"arg1": "edited"},
            "comment": "Fix arg1",
        }
        with patch("nexus.agent.hitl.interrupt", return_value=return_value):
            decision = interrupt_for_approval({"dummy": True})
        assert decision["action"] == "edit"
        assert decision["edited_inputs"] == {"arg1": "edited"}
        assert decision["comment"] == "Fix arg1"

    async def test_defaults_to_approve(self) -> None:
        with patch("nexus.agent.hitl.interrupt", return_value={"unknown": True}):
            decision = interrupt_for_approval({"dummy": True})
        assert decision["action"] == "approve"
