"""Test that _EPHEMERAL_FIELDS matches AgentState TypedDict keys.

_EPHEMERAL_FIELDS is the list of fields cleared between conversation turns.
If a new _-prefixed field is added to AgentState but not added to this list,
that field's value from turn N silently leaks into turn N+1 — routing bugs
follow.

This test compares the two sources at module import time and fails on any
mismatch, so no one can forget to keep them in sync.
"""

from nexus.agent.state_schema import AgentState, _EPHEMERAL_FIELDS


# Keys that are intentionally persistent (NOT ephemeral) despite having '_' prefix.
# These carry cross-turn context and must NOT be cleared between invocations.
_INTENTIONALLY_PERSISTENT = frozenset({
    "_structured_context",
    "_ir_stack",
    "_context_version",
    # P1-B.1: checkpoint compatibility contract — must survive to be read
    # by the NEXT invocation's load contract.
    "_contract_meta",
    # NOTE: _context_snapshot is NOT in this set — the comment in state_schema.py
    # declares it IS ephemeral ("rebuilt each turn from AgentState checkpoint").
    "_logical_workflow",
    "_execution_graph",
    "_optimization_snapshots",
    "_graph_version",
    "_cost_estimate",
    "_latency_estimate_ms",
    "_within_budget",
    "_estimate_warnings",
    "_aggregated_results",
    "_graph_patch",
    "_memory_persisted",
    # Interactive workflow context — MUST persist across turns so the
    # state machine can resume (active id, definition, collected values).
    "_active_workflow_id",
    "_workflow_type",
    "_workflow_step",
    "_workflow_steps_total",
    "_workflow_collected",
    "_workflow_history",
    "_workflow_next_action",
    "_workflow_definition",
    "_workflow_completed_steps",
    "_workflow_captured",
    # Hybrid execution markers — persist until the dynamic step is captured
    "_workflow_dynamic_pending",
    "_workflow_dynamic_intent",
    # Conversational approval checkpoint — persists until decided in-chat
    "_approval_pending",
    "_approval_checkpoint_context",
    "_approval_modification",
})

# Flat backward-compat fields that are maintained at runtime and do not have
# '_' prefix in AgentState. They ARE in _EPHEMERAL_FIELDS but won't have
# '_'-prefixed annotations.
_KNOWN_FLAT_EPHEMERAL = frozenset({"errors", "tool_results"})


def _get_ephemeral_keys() -> set[str]:
    """Extract all _-prefixed keys from the AgentState TypedDict annotations,
    excluding those that are intentionally persistent."""
    annotations = AgentState.__annotations__
    return {k for k in annotations if k.startswith("_") and k not in _INTENTIONALLY_PERSISTENT}


def test_ephemeral_fields_match_annotations():
    underscore_keys = _get_ephemeral_keys()
    ephemeral_set = set(_EPHEMERAL_FIELDS)

    # Keys declared in AgentState but missing from _EPHEMERAL_FIELDS
    missing_from_list = underscore_keys - ephemeral_set
    assert not missing_from_list, (
        f"Keys with '_' prefix exist in AgentState but are NOT in _EPHEMERAL_FIELDS: "
        f"{missing_from_list}. Add them to _EPHEMERAL_FIELDS in state_schema.py."
    )

    # Keys in _EPHEMERAL_FIELDS but NOT declared in AgentState annotations
    extra_in_list = ephemeral_set - underscore_keys - _KNOWN_FLAT_EPHEMERAL
    assert not extra_in_list, (
        f"Keys in _EPHEMERAL_FIELDS but NOT declared in AgentState: "
        f"{extra_in_list}. Either add them to AgentState or remove from _EPHEMERAL_FIELDS."
    )


def test_structured_context_not_ephemeral():
    """StructuredContext is the Single Source of Truth.

    It MUST persist across turns for cross-turn context accumulation.
    If it's in _EPHEMERAL_FIELDS, it gets cleared every turn.
    """
    assert "_structured_context" not in _EPHEMERAL_FIELDS, (
        "_structured_context is in _EPHEMERAL_FIELDS! "
        "It must NOT be ephemeral — remove it from the list."
    )
