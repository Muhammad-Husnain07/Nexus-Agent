"""Tests for the recovery/background/streaming lifecycle (final gaps)."""

from __future__ import annotations

import asyncio

import pytest

from nexus.agent.recovery import RecoveryAction, RecoveryManager
from nexus.events.models import StepProgressEvent, build_event
from nexus.execution.lifecycle import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
)


# ---------------------------------------------------------------------------
# ExecutionRequest / ExecutionResult lifecycle contracts
# ---------------------------------------------------------------------------


def test_execution_request_frozen_and_versioned():
    request = ExecutionRequest(
        execution_id="e1", session_id="s1", message="hello",
        execution_plan_version=1, resolver_version=1, planner_version=3,
        compiler_version=2, registry_version=7,
    )
    assert request.planner_version == 3
    assert request.compiler_version == 2
    try:
        request.message = "other"  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except Exception:
        pass


def test_execution_result_typed():
    result = ExecutionResult(
        execution_id="e1",
        status=ExecutionStatus.COMPLETED,
        final_response="done",
        progress_lines=["Waiting: x", "Done: x"],
        duration_ms=120,
    )
    assert result.status == ExecutionStatus.COMPLETED
    assert len(result.progress_lines) == 2
    try:
        result.final_response = "other"  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except Exception:
        pass


def test_execution_status_ladder_complete():
    expected = {
        "queued", "running", "waiting", "approval", "retrying",
        "completed", "failed", "cancelled", "skipped",
    }
    assert {s.value for s in ExecutionStatus} == expected


# ---------------------------------------------------------------------------
# StepProgress event (stable UI contract)
# ---------------------------------------------------------------------------


def test_step_progress_event_statuses():
    for status in ("queued", "running", "approval", "retrying", "completed", "failed", "skipped"):
        event = build_event("step_progress", {
            "step": "t1", "status": status, "text": "x", "tool_name": "tool",
        })
        assert event.payload["status"] == status


def test_step_progress_rejects_unknown_status():
    event = build_event("step_progress", {"step": "t1", "status": "bogus", "text": "x", "tool_name": "t"})
    # Validation failure falls back to an untyped passthrough (never crashes
    # the stream) — the payload is preserved as-is.
    assert event.payload["status"] == "bogus"


# ---------------------------------------------------------------------------
# RecoveryManager — one decision point, four strategies
# ---------------------------------------------------------------------------


def _transient_failure() -> dict:
    return {"tool_name": "x", "status": "timeout", "error": "timed out"}


def _structural_failure() -> dict:
    return {"tool_name": "y", "status": "validation_error", "error": "output validation: contract failed"}


def test_recovery_transient_retries():
    mgr = RecoveryManager(max_replan_rounds=1)
    d = mgr.decide([_transient_failure()], transient_retries_left=2)
    assert d.action == RecoveryAction.RETRY


def test_recovery_transient_without_budget_fails():
    mgr = RecoveryManager(max_replan_rounds=1)
    d = mgr.decide([_transient_failure()], transient_retries_left=0)
    assert d.action == RecoveryAction.FAIL


def test_recovery_structural_replans():
    mgr = RecoveryManager(max_replan_rounds=1)
    d = mgr.decide([_structural_failure()], transient_retries_left=2)
    assert d.action == RecoveryAction.REPLAN


def test_recovery_contract_with_fallback_self_heals():
    mgr = RecoveryManager(max_replan_rounds=1)
    d = mgr.decide([_structural_failure()], has_fallback_candidates=True, transient_retries_left=0)
    assert d.action == RecoveryAction.SELF_HEAL


def test_recovery_approval_blocking_replans():
    mgr = RecoveryManager(max_replan_rounds=1)
    d = mgr.decide([], approval_blocked=True)
    assert d.action == RecoveryAction.REPLAN
    assert "approval denied" in d.reason


def test_recovery_budget_violation_replans():
    mgr = RecoveryManager(max_replan_rounds=1)
    d = mgr.decide([], budget_violated=True)
    assert d.action == RecoveryAction.REPLAN
    assert "budget" in d.reason


def test_recovery_rounds_exhausted_fails():
    mgr = RecoveryManager(max_replan_rounds=1)
    d = mgr.decide([_structural_failure()], replan_rounds=1)
    assert d.action == RecoveryAction.FAIL
    assert "exhausted" in d.reason


def test_recovery_no_failures_fails_explicitly():
    mgr = RecoveryManager(max_replan_rounds=1)
    d = mgr.decide([])
    assert d.action == RecoveryAction.FAIL


def test_recovery_timeout_not_structural():
    assert RecoveryManager._is_structural(_transient_failure()) is False
    assert RecoveryManager._is_contract(_transient_failure()) is False


def test_recovery_contract_not_hard_structural():
    """Contract failures are healable via fallback — not hard structural."""
    assert RecoveryManager._is_structural(_structural_failure()) is False
    assert RecoveryManager._is_contract(_structural_failure()) is True
    # Typed status contract (no error-text pattern matching): an
    # ``unavailable`` status (tripped circuit / disabled provider) is hard
    # structural; a generic ``error`` status is not.
    hard = {"tool_name": "z", "status": "unavailable", "error": "provider unavailable"}
    assert RecoveryManager._is_structural(hard) is True
    generic = {"tool_name": "z", "status": "error", "error": "provider unavailable"}
    assert RecoveryManager._is_structural(generic) is False


# ---------------------------------------------------------------------------
# ReplanNode
# ---------------------------------------------------------------------------


def test_replan_node_context(monkeypatch):
    from nexus.agent.nodes.replan_node import ReplanNode

    node = ReplanNode()
    out = asyncio.run(node({
        "_executor_failed": ["op_a"],
        "_completed_tools": ["op_b"],
        "_replan_rounds": 0,
    }))
    assert out["_replan_context"]["unavailable_ops"] == ["op_a"]
    assert out["_replan_context"]["completed_tools"] == ["op_b"]
    assert out["_replan_rounds"] == 1
    assert out["_needs_replan"] is False


# ---------------------------------------------------------------------------
# Denial-blocking helper (approval rule)
# ---------------------------------------------------------------------------


def test_denial_blocks_graph_depends_on():
    from nexus.agent.nodes.approval_checkpoint_resume_node import _denial_blocks_graph

    graph = {
        "nodes": {
            "a": {"tool_name": "gen_report", "depends_on": [], "symbolic_ref": "StepA"},
            "b": {"tool_name": "email_report", "depends_on": ["a"], "symbolic_ref": "StepB"},
        }
    }
    assert _denial_blocks_graph(graph, {"email_report"}) is False  # leaf denial
    assert _denial_blocks_graph(graph, {"gen_report"}) is True     # blocks dependent


def test_denial_blocks_graph_placeholder():
    from nexus.agent.nodes.approval_checkpoint_resume_node import _denial_blocks_graph

    graph = {
        "nodes": {
            "a": {"tool_name": "gen_report", "depends_on": [], "symbolic_ref": "StepA"},
            "b": {"tool_name": "send_email", "depends_on": [], "symbolic_ref": "StepB",
                  "inputs": {"to": "x", "report": "${StepA.result.report}"}},
        }
    }
    assert _denial_blocks_graph(graph, {"gen_report"}) is True
    assert _denial_blocks_graph(graph, {"send_email"}) is False
