"""FE Step 1.5 — approval-pending read model (GET /sessions/{id}/state).

The server owns approvals (binding + expiry); a refreshed browser must be
able to reconstruct the approval UX from the state endpoint — the read
model is sanitized (no operation_hash) and reflects server-side expiry.
"""

from __future__ import annotations

import time

from nexus.api.chat import _approval_pending_read_model


def _pending(**overrides) -> dict:
    base = {
        "policy": "risky",
        "step": "step_0",
        "message": "Approve delete_users?",
        "context": "This will perform: POST delete_users",
        "tools": ["delete_users"],
        "tool_details": {"delete_users": {"method": "POST", "inputs": {"user_ids": ["1"]}}},
        "requested_at": time.time(),
        "operation_hash": "secret-binding-hash",
    }
    base.update(overrides)
    return base


class TestApprovalPendingReadModel:
    def test_none_when_no_pending(self):
        assert _approval_pending_read_model({}) is None
        assert _approval_pending_read_model({"messages": []}) is None
        assert _approval_pending_read_model({"_approval_pending": None}) is None

    def test_exposes_open_approval_with_expiry(self):
        model = _approval_pending_read_model({"_approval_pending": _pending()})
        assert model is not None
        assert model["policy"] == "risky"
        assert model["step"] == "step_0"
        assert model["tools"] == ["delete_users"]
        assert model["tool_details"]["delete_users"]["method"] == "POST"
        assert isinstance(model["requested_at"], (int, float))
        assert isinstance(model["expires_at"], float)
        assert model["expires_at"] > model["requested_at"]
        assert model["expired"] is False

    def test_sanitizes_operation_hash(self):
        model = _approval_pending_read_model({"_approval_pending": _pending()})
        assert "operation_hash" not in model
        assert "secret-binding-hash" not in str(model)

    def test_expired_flag_from_server_clock(self):
        model = _approval_pending_read_model({
            "_approval_pending": _pending(requested_at=time.time() - 4000),
        })
        assert model is not None
        assert model["expired"] is True

    def test_malformed_pending_never_raises(self):
        assert _approval_pending_read_model({"_approval_pending": "oops"}) is None
        assert _approval_pending_read_model({"_approval_pending": {"tools": None}}) is not None
