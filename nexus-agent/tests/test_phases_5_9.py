"""Tests for Phases 5–9: memory lifecycle, event models, contracts, context."""

from __future__ import annotations

import pytest

from nexus.capabilities.resolution_result import (
    CapabilityCandidate,
    ResolutionMetadata,
    ResolutionResult,
    WorkflowCandidate,
)
from nexus.events.models import ErrorEvent, ToolCallEvent, build_event
from nexus.execution.contract import (
    contract_from_metadata,
    contract_from_plan_node,
    contract_from_tool,
    contract_from_workflow,
)
from nexus.execution.context import ExecutionContext, StatePatch
from nexus.memory.scout import MemoryRetrievalResult, TRIGGER_PLANNING

# ---------------------------------------------------------------------------
# Phase 5 — Memory lifecycle (typed result + trigger)
# ---------------------------------------------------------------------------


def test_memory_retrieval_result_typed_and_bounded():
    result = MemoryRetrievalResult(snippets=("<memory>a</memory>",), count=1)
    assert result.count == 1
    assert result.truncated is False
    assert "<planning_memories>" in result.as_text
    empty = MemoryRetrievalResult()
    assert empty.as_text == ""


def test_planning_trigger_constant():
    assert TRIGGER_PLANNING == "planning"


# ---------------------------------------------------------------------------
# Phase 7 — Typed event models
# ---------------------------------------------------------------------------


def test_tool_call_event_typed():
    event = build_event("tool_call_completed", {
        "tool_name": "get_current_weather",
        "status": "success",
        "duration_ms": 12.5,
        "retries": 1,
        "cached": True,
    })
    assert event.type == "tool_call_completed"
    assert event.payload["cached"] is True
    assert event.payload["retries"] == 1


def test_error_event_typed():
    event = build_event("error", {"message": "boom", "tool_name": "x"})
    assert event.payload["message"] == "boom"


def test_event_model_validation_falls_back_safely():
    """Unknown event types pass through untyped (never crash the stream)."""
    event = build_event("custom_event", {"anything": 1})
    assert event.payload == {"anything": 1}


def test_event_models_frozen():
    err = ErrorEvent(message="x")
    try:
        err.message = "y"  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Phase 9 — ExecutionContract + normalizers
# ---------------------------------------------------------------------------


class _FakeTool:
    name = "get_current_weather"
    idempotent = True
    risk_level = "high"
    requires_approval = True
    cacheable = False
    input_schema = {"type": "object", "properties": {"latitude": {"type": "number"}}}
    output_schema = {"type": "object", "properties": {"temperature": {"type": "number"}}}
    produces = ["weather_data"]
    compensating_operation = "noop"


def test_contract_from_tool():
    c = contract_from_tool(_FakeTool())
    assert c.executable_type == "capability"
    assert c.name == "get_current_weather"
    assert "latitude" in c.inputs
    assert "temperature" in c.outputs
    assert c.policies.idempotent is True
    assert c.policies.risk_level == "high"
    assert c.checkpoint is True  # requires_approval → checkpoint
    assert c.expected_artifacts == ("weather_data",)
    assert c.rollback == "noop"


def test_contract_from_workflow():
    wf = {"name": "invoice_flow", "steps": [{"id": "s1", "intent": "get_invoice"}]}
    c = contract_from_workflow(wf)
    assert c.executable_type == "workflow"
    assert "workflow:s1" in c.expected_artifacts


def test_contract_from_plan_node():
    node = {"op": "send_email", "kind": "capability", "inputs": {"to": "x"}}
    c = contract_from_plan_node(node)
    assert c.name == "send_email"
    assert c.inputs == {"to": "x"}


def test_contract_from_metadata_defaults_never_guess():
    c = contract_from_metadata("a", "macro", contract_block=None)
    assert c.policies.risk_level == "low"
    assert c.timeout_s == 20.0
    assert c.checkpoint is False


def test_contract_frozen():
    c = contract_from_tool(_FakeTool())
    try:
        c.name = "other"  # type: ignore[misc]
        raise AssertionError("should be frozen")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Phase 9 — Unified executable candidates
# ---------------------------------------------------------------------------


def test_resolution_result_executable_candidates_unified():
    meta = ResolutionMetadata(elapsed_ms=1.0, catalog_size=1, fingerprint="f", registry_version=1)
    cap = CapabilityCandidate(id="1", name="get_weather", score=0.9, confidence="high")
    wf = WorkflowCandidate(
        id="2", name="invoice_flow", score=0.8, confidence="medium", executable_type="workflow"
    )
    result = ResolutionResult(
        query="q",
        capability_candidates=(cap,),
        workflow_candidates=(wf,),
        metadata=meta,
        has_capability_candidates=True,
        has_workflow_candidates=True,
    )
    exes = result.executable_candidates
    assert [e.executable_type for e in exes] == ["capability", "workflow"]
    assert [e.name for e in exes] == ["get_weather", "invoice_flow"]


# ---------------------------------------------------------------------------
# Phase 9 — ExecutionContext enrichment
# ---------------------------------------------------------------------------


def test_context_apply_derives_typed_views():
    ctx = ExecutionContext(version=0, parent_version=0, snapshot={})
    patch = StatePatch(
        version=1,
        updates={
            "_cost_estimate": 1.25,
            "_latency_estimate_ms": 400,
            "_within_budget": False,
            "_execution_strategy": "parallel",
            "_plan_validator_action": "proceed",
        },
    )
    next_ctx = ctx.apply(patch)
    assert next_ctx.budget["cost_estimate_usd"] == 1.25
    assert next_ctx.budget["within_budget"] is False
    assert next_ctx.strategy == "parallel"
    assert next_ctx.checkpoints["plan_validator"] == "proceed"
    # Immutability: the original is unchanged.
    assert ctx.budget == {}
    assert ctx.strategy == ""


def test_context_branch_carries_typed_views():
    ctx = ExecutionContext(version=2, parent_version=1, snapshot={}, budget={"x": 1}, strategy="map")
    branch = ctx.branch()
    assert branch.strategy == "map"
    assert branch.budget == {"x": 1}
