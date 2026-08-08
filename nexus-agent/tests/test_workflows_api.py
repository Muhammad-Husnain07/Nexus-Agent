"""Tests for the workflows API schemas and template-engine definition matching.

Covers:
- WorkflowDefinitionCreate step validation (id uniqueness, executable step)
- WorkflowDefinitionUpdate step validation
- Serialization round-trip
- Template engine matching consults developer-registered WorkflowDefinition rows
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from nexus.api.workflows import (
    WorkflowDefinitionCreate,
    WorkflowDefinitionUpdate,
    WorkflowStep,
    _workflow_to_dict,
)
from nexus.db.models.workflow_definition import WorkflowDefinition


def _valid_steps() -> list[dict[str, Any]]:
    return [
        {"id": "step_1", "description": "Fetch", "intent": "get_invoice"},
        {"id": "step_2", "description": "Approve", "intent": "approve_invoice"},
    ]


def test_create_valid_workflow():
    wf = WorkflowDefinitionCreate(
        name="invoice_approval",
        trigger_intent_pattern="approve invoice",
        steps=[WorkflowStep(**s) for s in _valid_steps()],
        priority=5,
    )
    assert wf.name == "invoice_approval"
    assert len(wf.steps) == 2


def test_create_rejects_duplicate_step_ids():
    steps = _valid_steps()
    steps[1]["id"] = "step_1"
    with pytest.raises(ValidationError):
        WorkflowDefinitionCreate(name="x", steps=[WorkflowStep(**s) for s in steps])


def test_create_rejects_step_without_executable_instruction():
    steps = [{"id": "step_1", "description": "nothing"}]
    with pytest.raises(ValidationError):
        WorkflowDefinitionCreate(name="x", steps=[WorkflowStep(**s) for s in steps])


def test_create_accepts_dynamic_and_workflow_ref_steps():
    steps = [
        {"id": "step_1", "description": "Ask", "dynamic": True, "question": "Which table?"},
        {"id": "step_2", "description": "Reuse", "workflow_ref": "onboarding"},
    ]
    wf = WorkflowDefinitionCreate(name="hybrid", steps=[WorkflowStep(**s) for s in steps])
    assert wf.steps[0].dynamic is True
    assert wf.steps[1].workflow_ref == "onboarding"


def test_create_accepts_requires_input_only_step():
    """An input-collection step (asks the user in-chat) needs no executable kind."""
    steps = [{"id": "step_1", "description": "Ask", "requires_input": True, "question": "Which id?"}]
    wf = WorkflowDefinitionCreate(name="collector", steps=[WorkflowStep(**s) for s in steps])
    assert wf.steps[0].requires_input is True


def test_update_validates_steps_too():
    with pytest.raises(ValidationError):
        WorkflowDefinitionUpdate(steps=[{"id": "step_1", "description": "bad"}])


def test_serialization_round_trip():
    wf = WorkflowDefinition(
        name="roundtrip",
        description="d",
        trigger_intent_pattern="p",
        steps=_valid_steps(),
        priority=1,
        max_nodes=10,
        enabled=True,
        version=3,
    )
    data = _workflow_to_dict(wf)
    assert data["name"] == "roundtrip"
    assert data["version"] == 3
    assert data["steps"] == _valid_steps()
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_template_engine_matches_workflow_definitions(monkeypatch):
    """match_templates returns steps from registered WorkflowDefinition rows."""
    from nexus import capabilities
    from nexus.capabilities import template_engine as te

    # Build a fake definition row matching "approve invoice"
    wf = WorkflowDefinition(
        name="invoice_approval",
        trigger_intent_pattern="approve invoice",
        steps=_valid_steps(),
        enabled=True,
        priority=10,
    )

    class _FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [wf]

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, stmt):  # noqa: ARG002
            return _FakeResult()

    def fake_session_factory():
        return _FakeSession()

    monkeypatch.setattr(te, "_async_session", fake_session_factory)

    chains = await te.match_templates("please approve invoice 42")
    assert len(chains) == 1
    assert chains[0][0]["intent"] == "get_invoice"
