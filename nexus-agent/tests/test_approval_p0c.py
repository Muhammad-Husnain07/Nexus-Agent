"""C2/P0-C approval-binding adversarial tests.

The invariant: an approval authorizes the EXACT operation recorded when it
was requested — a modified/replanned operation (different inputs, plan
version, capability set) must never be auto-authorized.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from nexus.agent.nodes.multi_approval_gate_node import _process_approval_chain

POLICY = {
    "id": "pol-1",
    "name": "risky",
    "version": "2",
    "steps": [
        {
            "step_id": "step_0",
            "role": "operator",
            "inputs": {},
        }
    ],
}

TOOL_NAMES = ["delete_users"]
TOOL_DETAILS = {
    "delete_users": {
        "method": "POST",
        "inputs": {"user_ids": ["1", "2", "3"]},
        "capability_id": "cap-delete",
    },
}


def _pending(operation_hash: str) -> dict:
    return {
        "policy": "risky",
        "step": "step_0",
        "message": "approve?",
        "context": "",
        "tools": TOOL_NAMES,
        "tool_details": TOOL_DETAILS,
        "requested_at": 1.0,
        "operation_hash": operation_hash,
    }


def _hash_of(step_inputs: dict | None, resolved: dict | None, graph_version: str = "1") -> str:
    payload = {
        "policy": "risky",
        "policy_version": "2",
        "step": "step_0",
        "tools": sorted(TOOL_NAMES),
        "step_inputs": {str(k): str(v) for k, v in (step_inputs or {}).items()},
        "resolved_inputs": {k: v for k, v in sorted((resolved or {}).items())},
        "capability_ids": ["cap-delete"],
        "graph_version": graph_version,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()[:24]


class TestC2ApprovalBinding:
    def _state(self, decision, chain, pending) -> dict:
        return {
            "_approval_decision": decision,
            "_approval_chain_state": chain,
            "_approval_pending": pending,
            "_graph_version": "1",
        }

    def test_approve_unchanged_operation_grants(self):
        h = _hash_of(None, {"delete_users": {"user_ids": "['1', '2', '3']"}})
        state = self._state(
            "approved",
            {"step_step_0_decision": "approved", "step_step_0_hash": h},
            _pending(h),
        )
        result = asyncio.run(
            _process_approval_chain(state, POLICY, TOOL_NAMES, TOOL_DETAILS)
        )
        assert result["_approval_granted"] is True
        assert result["_approval_decision"] is None, (
            "the decision must be consumed after granting"
        )

    def test_approve_modified_operation_requires_new_approval(self):
        """Approve operation A (inputs 1-3); the plan changes to inputs
        4-6 → the operation hash differs → the approval must NOT hold."""
        original_h = _hash_of(None, {"delete_users": {"user_ids": "['1', '2', '3']"}})
        modified_h = _hash_of(None, {"delete_users": {"user_ids": "['4', '5', '6']"}})
        assert original_h != modified_h
        state = self._state(
            "approved",
            {"step_step_0_decision": "approved", "step_step_0_hash": original_h},
            _pending(modified_h),
        )
        result = asyncio.run(
            _process_approval_chain(state, POLICY, TOOL_NAMES, TOOL_DETAILS)
        )
        assert result["_approval_granted"] is False, (
            "a modified operation must never be auto-authorized"
        )
        assert result["_needs_approval"] is True, (
            "a new approval must be requested"
        )
        assert result["_approval_decision"] is None, (
            "the stale decision must be consumed"
        )

    def test_approve_modified_graph_version_requires_new_approval(self):
        """The plan version participates in the binding — a replanned
        graph (even with identical inputs) is a different operation."""
        original_h = _hash_of(None, {"delete_users": {"user_ids": "['1', '2', '3']"}}, "1")
        replanned_h = _hash_of(None, {"delete_users": {"user_ids": "['1', '2', '3']"}}, "2")
        assert original_h != replanned_h
        state = self._state(
            "approved",
            {"step_step_0_decision": "approved", "step_step_0_hash": original_h},
            _pending(replanned_h),
        )
        result = asyncio.run(
            _process_approval_chain(state, POLICY, TOOL_NAMES, TOOL_DETAILS)
        )
        assert result["_approval_granted"] is False

    def test_unbound_decision_is_never_honored(self):
        """A stored decision without a matching bound hash grants nothing."""
        h = _hash_of(None, {"delete_users": {"user_ids": "['1', '2', '3']"}})
        state = self._state(
            "approved",
            {"step_step_0_decision": "approved"},  # no step_step_0_hash recorded
            _pending(h),
        )
        result = asyncio.run(
            _process_approval_chain(state, POLICY, TOOL_NAMES, TOOL_DETAILS)
        )
        assert result["_approval_granted"] is False

    def test_reject_is_unconditional(self):
        state = self._state("rejected", {}, _pending("x" * 24))
        result = asyncio.run(
            _process_approval_chain(state, POLICY, TOOL_NAMES, TOOL_DETAILS)
        )
        assert result["_approval_granted"] is False
        assert result["_needs_approval"] is False

    def test_operation_hash_tracks_resolved_inputs(self):
        """Two approval requests with different resolved tool inputs must
        produce different operation hashes."""
        state_a = {
            "_approval_decision": None,
            "_approval_chain_state": {},
            "_approval_pending": None,
            "_graph_version": "1",
        }
        details_a = {
            "delete_users": {"method": "POST", "inputs": {"user_ids": ["1"]}, "capability_id": "cap-delete"},
        }
        result_a = asyncio.run(
            _process_approval_chain(state_a, POLICY, TOOL_NAMES, details_a)
        )
        state_b = {
            "_approval_decision": None,
            "_approval_chain_state": {},
            "_approval_pending": None,
            "_graph_version": "1",
        }
        details_b = {
            "delete_users": {"method": "POST", "inputs": {"user_ids": ["9"]}, "capability_id": "cap-delete"},
        }
        result_b = asyncio.run(
            _process_approval_chain(state_b, POLICY, TOOL_NAMES, details_b)
        )
        hash_a = result_a["_approval_pending"]["operation_hash"]
        hash_b = result_b["_approval_pending"]["operation_hash"]
        assert hash_a != hash_b

