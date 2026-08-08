"""Closing coverage tests — background handoff, routing functions,
planner replan-scoping, approval reject-blocking integration."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nexus.agent.graph import (
    route_after_checkpoint,
    route_after_recovery,
)
from nexus.agent.nodes.approval_checkpoint_resume_node import (
    _classify_approval_reply,
    _denial_blocks_graph,
    approval_checkpoint_resume_node,
)
from nexus.agent.nodes.semantic_parser_node import _scope_out_unavailable
from nexus.execution.context import ExecutionContext


# ---------------------------------------------------------------------------
# Route functions (deterministic)
# ---------------------------------------------------------------------------


def test_route_after_recovery_matrix():
    assert route_after_recovery({"_recovery_decision": {"action": "retry"}}) == "ReflectionNode"
    assert route_after_recovery({"_recovery_decision": {"action": "replan"}}) == "ReplanNode"
    assert route_after_recovery({"_recovery_decision": {"action": "fail"}}) == "ResponseNode"
    assert route_after_recovery({}) == "ResponseNode"  # safe default


def test_route_after_checkpoint_replan_branch():
    assert route_after_checkpoint({"_routing_decision": "replan"}) == "SemanticPlannerNode"
    assert route_after_checkpoint({"_route_to_gate": True}) == "ApprovalGateNode"
    assert route_after_checkpoint({"_route_to_planner": True}) == "SemanticPlannerNode"
    assert route_after_checkpoint({}) == "ResponseNode"


# ---------------------------------------------------------------------------
# Planner replan-scoping
# ---------------------------------------------------------------------------


def test_scope_out_unavailable():
    ops = ["a", "b", "c"]
    assert _scope_out_unavailable(ops, None) == ops
    assert _scope_out_unavailable(ops, {}) == ops
    assert _scope_out_unavailable(ops, {"unavailable_ops": ["b"]}) == ["a", "c"]
    # Never empty-out the whole catalog (replan must keep a fallback).
    assert _scope_out_unavailable(["b"], {"unavailable_ops": ["b"]}) == ["b"]


# ---------------------------------------------------------------------------
# Background handoff (executor_node branch)
# ---------------------------------------------------------------------------


async def test_executor_node_background_handoff(monkeypatch):
    """When the estimator marked the run for background execution, the
    executor enqueues an ExecutionRequest and does NOT execute inline."""
    from nexus.agent.graph import executor_node

    class _FakeTaskRegistry:
        async def create(self, task_type, payload, session_id=None, **kwargs):
            assert task_type == "workflow_run"
            assert payload["execution_id"]
            assert payload["resolver_version"] >= 1
            assert payload["planner_version"] >= 1
            assert payload["compiler_version"] >= 1
            return {"id": "bg-task-123"}

    monkeypatch.setattr(
        "nexus.tasks.registry.TaskRegistry", lambda: _FakeTaskRegistry()
    )
    state = {
        "_background_execution": True,
        "session_id": "s1",
        "messages": [{"role": "user", "content": "run heavy job"}],
        "_execution_graph": {
            "nodes": {"n1": {"tool_name": "heavy_tool", "kind": "tool"}},
            "waves": [["n1"]],
        },
        "tool_results": [],
    }
    out = await executor_node(state, tool_executor=None)  # type: ignore[arg-type]
    assert out["_background_task_id"] == "bg-task-123"
    assert out["response_type"] == "background"
    assert "_executor_failed" in out
    assert out["_executor_all_success"] is True


async def test_executor_node_inline_unchanged(monkeypatch):
    """Without the background flag, execution proceeds (no task created)."""
    from nexus.agent.graph import executor_node

    called = {"create": False}

    class _FakeTaskRegistry:
        async def create(self, task_type, payload, session_id=None, **kwargs):
            called["create"] = True
            return {"id": "x"}

    monkeypatch.setattr("nexus.tasks.registry.TaskRegistry", lambda: _FakeTaskRegistry())
    state = {
        "_background_execution": False,
        "session_id": "s1",
        "messages": [],
        "_optimized_graph": {
            "nodes": {"n1": {"tool_name": "heavy_tool", "kind": "tool"}},
            "waves": [],
        },
        "tool_results": [],
    }
    # Without a real executor the inline path errors out — the point is that
    # the background branch (and task creation) was NOT taken.
    out = await executor_node(state, tool_executor=None)  # type: ignore[arg-type]
    assert called["create"] is False
    assert out.get("_background_task_id") is None


# ---------------------------------------------------------------------------
# Approval reject-blocking integration
# ---------------------------------------------------------------------------


async def _reject_approval(snapshot: dict, monkeypatch) -> dict:
    """Run the resume node with the LLM classifier forced to 'reject'.

    The @context_node-decorated node receives a plain state dict and returns
    the state-update dict (old/new pattern conversion handled internally).
    """
    monkeypatch.setattr(
        "nexus.agent.nodes.approval_checkpoint_resume_node._classify_approval_reply",
        _FakeClassify("reject"),
    )
    patch = await approval_checkpoint_resume_node(snapshot, llm=None, model="test")  # type: ignore[arg-type]
    if hasattr(patch, "updates"):
        return patch.updates
    return dict(patch or {})


class _FakeClassify:
    def __init__(self, intent: str) -> None:
        self._intent = intent

    async def __call__(self, *args, **kwargs):
        return self._intent


def _checkpoint_snapshot(tools: list[str], graph: dict) -> dict:
    return {
        "messages": [{"role": "user", "content": "no"}],
        "_approval_pending": {"tools": tools},
        "_approval_checkpoint": {"tools": tools},
        "_execution_graph": graph,
    }


async def test_reject_non_blocking_stops_gracefully(monkeypatch):
    graph = {
        "nodes": {
            "a": {"tool_name": "gen_report", "depends_on": [], "symbolic_ref": "StepA"},
            "b": {"tool_name": "email_report", "depends_on": ["a"], "symbolic_ref": "StepB"},
        }
    }
    updates = await _reject_approval(
        _checkpoint_snapshot(["email_report"], graph), monkeypatch
    )
    assert updates["_routing_decision"] == "finalize"
    assert "_replan_context" not in updates


async def test_reject_blocking_triggers_replan(monkeypatch):
    graph = {
        "nodes": {
            "a": {"tool_name": "gen_report", "depends_on": [], "symbolic_ref": "StepA"},
            "b": {"tool_name": "email_report", "depends_on": ["a"], "symbolic_ref": "StepB"},
        }
    }
    updates = await _reject_approval(
        _checkpoint_snapshot(["gen_report"], graph), monkeypatch
    )
    assert updates["_routing_decision"] == "replan"
    assert updates["_replan_context"]["unavailable_ops"] == ["gen_report"]
    assert "another way" in updates["final_response"]


async def test_reject_blocking_placeholder_signal(monkeypatch):
    graph = {
        "nodes": {
            "a": {"tool_name": "gen_report", "depends_on": [], "symbolic_ref": "StepA"},
            "b": {"tool_name": "send_email", "depends_on": [], "symbolic_ref": "StepB",
                  "inputs": {"report": "${StepA.result.report}"}},
        }
    }
    updates = await _reject_approval(
        _checkpoint_snapshot(["gen_report"], graph), monkeypatch
    )
    assert updates["_routing_decision"] == "replan"
