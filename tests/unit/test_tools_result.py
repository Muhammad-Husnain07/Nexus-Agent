"""Unit tests for ToolResult model."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from nexus.tools.result import RAW_RESPONSE_MAX_CHARS, ToolResult


class TestToolResult:
    def test_minimal_success(self) -> None:
        r = ToolResult(
            tool_id=uuid.uuid4(),
            tool_name="test",
            status="success",
            duration_ms=42,
        )
        assert r.status == "success"
        assert r.duration_ms == 42
        assert r.retried is False

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ToolResult(
                tool_id=uuid.uuid4(),
                tool_name="bad",
                status="invalid_status",  # type: ignore[arg-type]
                duration_ms=0,
            )

    def test_truncates_long_raw_response(self) -> None:
        long_body = "x" * (RAW_RESPONSE_MAX_CHARS + 100)
        r = ToolResult(
            tool_id=uuid.uuid4(),
            tool_name="test",
            status="success",
            duration_ms=0,
            raw_response_excerpt=long_body,
        )
        assert r.raw_response_excerpt is not None
        assert len(r.raw_response_excerpt) == RAW_RESPONSE_MAX_CHARS + 3  # + "..."
        assert r.raw_response_excerpt.endswith("...")

    def test_short_raw_response_not_truncated(self) -> None:
        body = "ok"
        r = ToolResult(
            tool_id=uuid.uuid4(),
            tool_name="test",
            status="success",
            duration_ms=0,
            raw_response_excerpt=body,
        )
        assert r.raw_response_excerpt == "ok"

    def test_error_result(self) -> None:
        r = ToolResult(
            tool_id=uuid.uuid4(),
            tool_name="failing",
            status="error",
            error="Connection refused",
            duration_ms=100,
            retried=True,
        )
        assert r.error == "Connection refused"
        assert r.retried is True
