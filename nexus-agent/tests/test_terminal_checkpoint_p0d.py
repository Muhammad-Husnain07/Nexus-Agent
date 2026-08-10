"""D2/P0-D — terminal checkpoint recovery (I6).

A terminal-abnormal invocation checkpoint must never silently continue the
old graph: the next invocation starts fresh planning/execution, and the
state endpoint reports the truthful terminal status.
"""

from __future__ import annotations

from nexus.agent.runner import _TERMINAL_ABNORMAL, _terminal_reset_needed
from nexus.api.chat import derive_run_status


class TestTerminalResetDecision:
    def test_terminal_abnormal_statuses_require_reset(self):
        for status in ("CANCELLED", "TIMED_OUT", "INTERRUPTED", "FAILED"):
            assert _terminal_reset_needed(status) is True, status

    def test_non_terminal_statuses_do_not_reset(self):
        for status in (None, "", "RUNNING", "COMPLETED"):
            assert _terminal_reset_needed(status) is False, str(status)

    def test_terminal_set_complete(self):
        assert frozenset(
            {"CANCELLED", "TIMED_OUT", "INTERRUPTED", "FAILED"}
        ) == _TERMINAL_ABNORMAL


class TestRunStatusMapping:
    def test_terminal_abnormal_reported_truthfully(self):
        assert derive_run_status(True, "TIMED_OUT") == "timed_out"
        assert derive_run_status(True, "INTERRUPTED") == "interrupted"
        assert derive_run_status(True, "CANCELLED") == "cancelled"
        assert derive_run_status(True, "FAILED") == "failed"

    def test_completed_marker_maps_to_completed(self):
        assert derive_run_status(True, "COMPLETED") == "completed"
        assert derive_run_status(False, None) == "completed"

    def test_active_run_reports_running(self):
        assert derive_run_status(True, "RUNNING") == "running"
        assert derive_run_status(True, None) == "running"
