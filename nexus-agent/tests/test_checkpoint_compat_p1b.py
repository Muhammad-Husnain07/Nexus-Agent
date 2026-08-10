"""P1-B.1 — checkpoint compatibility contract.

A checkpoint must NEVER be interpreted under a contract it was not created
for. Missing / mismatched compatibility metadata → refuse safely (no stale
graph execution, no state reinterpretation).
"""

from __future__ import annotations

from nexus.agent.runner import build_contract_meta, checkpoint_contract_ok


class TestContractMeta:
    def test_current_contract_is_stable(self):
        a = build_contract_meta()
        b = build_contract_meta()
        assert a == b, "the contract must be deterministic within a version"
        assert "arch_fp" in a
        assert "state_schema" in a

    def test_same_contract_resumes(self):
        meta = build_contract_meta()
        assert checkpoint_contract_ok({"_contract_meta": meta}) is None

    def test_missing_metadata_refuses(self):
        assert checkpoint_contract_ok({}) is not None
        assert checkpoint_contract_ok({"_contract_meta": None}) is not None
        assert checkpoint_contract_ok({"_contract_meta": {}}) is not None

    def test_architecture_mismatch_refuses(self):
        meta = dict(build_contract_meta())
        meta["arch_fp"] = "x" * 16
        reason = checkpoint_contract_ok({"_contract_meta": meta})
        assert reason == "architecture fingerprint mismatch"

    def test_state_schema_mismatch_refuses(self):
        meta = dict(build_contract_meta())
        meta["state_schema"] = "999"
        reason = checkpoint_contract_ok({"_contract_meta": meta})
        assert reason == "state schema version mismatch"

    def test_terminal_status_still_wins_on_compatible_checkpoint(self):
        """A compatible checkpoint with a terminal status is handled by the
        D2 terminal-reset semantics, not the contract (the contract check
        passes, so the reset path decides)."""
        meta = build_contract_meta()
        assert checkpoint_contract_ok({"_contract_meta": meta}) is None
        from nexus.agent.runner import _terminal_reset_needed

        assert _terminal_reset_needed("TIMED_OUT") is True
        assert _terminal_reset_needed("RUNNING") is False

    def test_contract_meta_schema_version_constant(self):
        from nexus.agent.state_schema import AGENT_STATE_SCHEMA_VERSION

        assert isinstance(AGENT_STATE_SCHEMA_VERSION, str)
        assert build_contract_meta()["state_schema"] == AGENT_STATE_SCHEMA_VERSION
