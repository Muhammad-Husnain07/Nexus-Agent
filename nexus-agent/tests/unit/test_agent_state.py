"""Unit tests for AgentState TypedDict and PlanStep model."""

from __future__ import annotations

from nexus.agent.state import AgentState, PlanStep


class TestPlanStep:
    """PlanStep model construction and serialisation."""

    def test_defaults(self) -> None:
        step = PlanStep(id="step_1", description="Test step")
        assert step.id == "step_1"
        assert step.description == "Test step"
        assert step.tool_name is None
        assert step.inputs is None
        assert step.status == "pending"
        assert step.depends_on == []

    def test_full_construction(self) -> None:
        step = PlanStep(
            id="step_2",
            description="Do something",
            tool_name="my_tool",
            inputs={"key": "value"},
            status="running",
            depends_on=["step_1"],
        )
        assert step.tool_name == "my_tool"
        assert step.inputs == {"key": "value"}
        assert step.status == "running"
        assert step.depends_on == ["step_1"]

    def test_serialisation(self) -> None:
        step = PlanStep(id="s1", description="test", tool_name="tool")
        d = step.model_dump(mode="json")
        assert d["id"] == "s1"
        assert d["status"] == "pending"
        assert d["tool_name"] == "tool"

        restored = PlanStep(**d)
        assert restored.id == step.id
        assert restored.status == step.status

    def test_status_literal(self) -> None:
        for status in ("pending", "running", "done", "failed", "skipped"):
            step = PlanStep(id="x", description="x", status=status)  # type: ignore[arg-type]
            assert step.status == status


class TestAgentState:
    """AgentState TypedDict structure."""

    def test_minimal_state(self) -> None:
        state: AgentState = {
            "messages": [{"role": "user", "content": "hello"}],
            "tenant_id": "tenant-1",
            "session_id": "session-1",
            "user_id": "user-1",
            "plan": None,
            "current_step_index": 0,
            "gathered_requirements": {},
            "available_tools": [],
            "pending_approval": None,
            "iteration_count": 0,
            "scratchpad": "",
            "tool_results": [],
            "final_response": None,
            "intent": None,
            "missing_info_slots": None,
            "errors": [],
            "_bound_tools": [],
            "_routing_decision": "continue",
        }
        assert state["tenant_id"] == "tenant-1"
        assert state["messages"][0]["content"] == "hello"
        assert state["final_response"] is None

    def test_with_plan(self) -> None:
        step = PlanStep(id="s1", description="step 1", tool_name="tool_a")
        state: AgentState = {
            "messages": [],
            "tenant_id": "t1",
            "session_id": "s1",
            "user_id": "u1",
            "plan": [step.model_dump(mode="json")],
            "current_step_index": 0,
            "gathered_requirements": {},
            "available_tools": [],
            "pending_approval": None,
            "iteration_count": 1,
            "scratchpad": "",
            "tool_results": [],
            "final_response": "done",
            "intent": {"intent": "test", "parameters": {}},
            "missing_info_slots": [],
            "errors": [],
            "_bound_tools": [],
            "_routing_decision": "finalize",
        }
        assert state["plan"] is not None
        assert len(state["plan"]) == 1
        assert state["plan"][0]["tool_name"] == "tool_a"
        assert state["final_response"] == "done"
        assert state["iteration_count"] == 1
