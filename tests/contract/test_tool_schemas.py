"""Contract tests — verify tool schemas, API response shapes, and message formats.

Ensures every registered tool's input/output schema is valid JSON Schema,
that example inputs validate against schemas, and that API responses
match declared Pydantic models.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest

from nexus.tools.schemas import (
    ToolCreate,
    ToolExample,
    ToolRead,
    ToolSearchResult,
    ToolVersionDiff,
)

pytestmark = [pytest.mark.contract]


class TestToolSchemas:
    """Validate that tool schemas are well-formed JSON Schema documents."""

    SAMPLE_TOOLS: list[dict[str, Any]] = [
        {
            "name": "send_email",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "format": "email"},
                    "subject": {"type": "string", "maxLength": 200},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["sent", "queued", "failed"]},
                },
                "required": ["message_id", "status"],
            },
            "examples": [
                {
                    "user_prompt": "Send an email to john@example.com",
                    "expected_tool": "send_email",
                    "sample_input": {"to": "john@example.com", "subject": "Hello", "body": "Just saying hi"},
                    "sample_output": {"message_id": "msg_123", "status": "sent"},
                }
            ],
        },
        {
            "name": "search_docs",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string", "minLength": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["q"]},
            "output_schema": {"type": "object", "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string", "format": "uri"}, "score": {"type": "number"}}}}, "total": {"type": "integer"}}},
            "examples": [{"user_prompt": "Find docs about deployment", "expected_tool": "search_docs", "sample_input": {"q": "deployment", "limit": 5}, "sample_output": {"results": [{"title": "Deployment Guide", "url": "/docs/deploy", "score": 0.95}], "total": 1}}],
        },
        {
            "name": "delete_user",
            "input_schema": {"type": "object", "properties": {"user_id": {"type": "string", "pattern": "^[0-9a-f-]{36}$"}, "confirm": {"type": "boolean"}}, "required": ["user_id", "confirm"]},
            "output_schema": {"type": "object", "properties": {"deleted": {"type": "boolean"}, "user_id": {"type": "string"}}, "required": ["deleted"]},
            "examples": [{"user_prompt": "Delete user abc-123", "expected_tool": "delete_user", "sample_input": {"user_id": "00000000-0000-0000-0000-000000000001", "confirm": True}, "sample_output": {"deleted": True, "user_id": "00000000-0000-0000-0000-000000000001"}}],
        },
        {
            "name": "create_report",
            "input_schema": {"type": "object", "properties": {"title": {"type": "string", "minLength": 1}, "format": {"type": "string", "enum": ["pdf", "csv", "xlsx"]}, "date_range": {"type": "object", "properties": {"start": {"type": "string", "format": "date"}, "end": {"type": "string", "format": "date"}}}}, "required": ["title", "format"]},
            "output_schema": {"type": "object", "properties": {"report_id": {"type": "string"}, "url": {"type": "string", "format": "uri"}, "status": {"type": "string"}}},
            "examples": [{"user_prompt": "Generate sales report", "expected_tool": "create_report", "sample_input": {"title": "Q1 Sales", "format": "pdf", "date_range": {"start": "2026-01-01", "end": "2026-03-31"}}, "sample_output": {"report_id": "rpt_001", "url": "/reports/rpt_001.pdf", "status": "generated"}}],
        },
        {
            "name": "list_tickets",
            "input_schema": {"type": "object", "properties": {"status": {"type": "string", "enum": ["open", "closed", "all"]}, "assignee": {"type": "string"}, "page": {"type": "integer", "minimum": 1}}, "required": []},
            "output_schema": {"type": "object", "properties": {"tickets": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "subject": {"type": "string"}, "status": {"type": "string"}}}}, "total": {"type": "integer"}}},
            "examples": [{"user_prompt": "Show open tickets", "expected_tool": "list_tickets", "sample_input": {"status": "open"}, "sample_output": {"tickets": [], "total": 0}}],
        },
        {
            "name": "schedule_meeting",
            "input_schema": {"type": "object", "properties": {"title": {"type": "string", "minLength": 1}, "date": {"type": "string", "format": "date"}, "time": {"type": "string", "pattern": "^[0-2]\\d:[0-5]\\d$"}, "attendees": {"type": "array", "items": {"type": "string"}}, "duration_minutes": {"type": "integer", "minimum": 15, "maximum": 480}}, "required": ["title", "date", "time"]},
            "output_schema": {"type": "object", "properties": {"meeting_id": {"type": "string"}, "calendar_link": {"type": "string"}}},
            "examples": [{"user_prompt": "Schedule meeting on Monday", "expected_tool": "schedule_meeting", "sample_input": {"title": "Team sync", "date": "2026-07-21", "time": "14:00", "attendees": ["a@t.com"], "duration_minutes": 30}, "sample_output": {"meeting_id": "mtg_001", "calendar_link": "/cal/mtg_001"}}],
        },
    ]

    @pytest.mark.parametrize("tool_data", SAMPLE_TOOLS)
    def test_input_schema_is_valid_json_schema(self, tool_data: dict[str, Any]) -> None:
        """Every tool's input_schema is a valid JSON Schema (draft 2020-12)."""
        schema = tool_data["input_schema"]
        assert "type" in schema, "input_schema must have a type"
        jsonschema.Draft202012Validator.check_schema(schema)

    @pytest.mark.parametrize("tool_data", SAMPLE_TOOLS)
    def test_output_schema_is_valid_json_schema(self, tool_data: dict[str, Any]) -> None:
        """Every tool's output_schema is a valid JSON Schema (draft 2020-12)."""
        schema = tool_data["output_schema"]
        assert "type" in schema, "output_schema must have a type"
        jsonschema.Draft202012Validator.check_schema(schema)

    @pytest.mark.parametrize("tool_data", SAMPLE_TOOLS)
    def test_example_inputs_validate_against_input_schema(
        self, tool_data: dict[str, Any]
    ) -> None:
        """Example inputs must pass validation against input_schema."""
        for example in tool_data.get("examples", []):
            jsonschema.validate(example["sample_input"], tool_data["input_schema"])

    @pytest.mark.parametrize("tool_data", SAMPLE_TOOLS)
    def test_example_outputs_validate_against_output_schema(
        self, tool_data: dict[str, Any]
    ) -> None:
        """Example outputs must pass validation against output_schema."""
        for example in tool_data.get("examples", []):
            jsonschema.validate(example["sample_output"], tool_data["output_schema"])

    @pytest.mark.parametrize("tool_data", SAMPLE_TOOLS)
    def test_required_fields_present_in_examples(self, tool_data: dict[str, Any]) -> None:
        """Required fields specified in input_schema are present in example inputs."""
        required = tool_data["input_schema"].get("required", [])
        for example in tool_data.get("examples", []):
            for field in required:
                assert field in example["sample_input"], (
                    f"Missing required field '{field}' in example input for {tool_data['name']}"
                )

    def test_schema_drift_detection(self) -> None:
        """Detect when a stored schema differs from the expected schema."""
        stored = {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
            },
            "required": ["to"],
        }
        expected = {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to"],
        }
        stored_keys = set(stored.get("properties", {}).keys())
        expected_keys = set(expected.get("properties", {}).keys())
        missing_keys = expected_keys - stored_keys
        assert missing_keys, "No drift detected (expected drift in test)"
        assert "body" in missing_keys


class TestPydanticModels:
    """Verify Pydantic model validation rules."""

    def test_tool_create_validates_name(self) -> None:
        """ToolCreate requires a non-empty name."""
        tool = ToolCreate(
            name="valid-name",
            description="test",
            purpose="test",
            endpoint_url="http://example.com",
            http_method="GET",
        )
        assert tool.name == "valid-name"

    def test_tool_create_accepts_valid_methods(self) -> None:
        """ToolCreate accepts standard HTTP methods."""
        for method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            tool = ToolCreate(
                name="test",
                description="test",
                purpose="test",
                endpoint_url="http://example.com",
                http_method=method,
            )
            assert tool.http_method == method

    def test_tool_example_roundtrip(self) -> None:
        """ToolExample serializes and deserializes correctly."""
        example = ToolExample(
            user_prompt="Test prompt",
            expected_tool="test_tool",
            sample_input={"key": "val"},
            sample_output={"result": "ok"},
        )
        data = example.model_dump(mode="json")
        restored = ToolExample(**data)
        assert restored.user_prompt == example.user_prompt
        assert restored.expected_tool == example.expected_tool

    def test_tool_search_result_score_range(self) -> None:
        """ToolSearchResult score must be between 0 and 1."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ToolSearchResult(tool=None, score=1.5)  # type: ignore[arg-type]

    def test_version_diff_changed_fields(self) -> None:
        """ToolVersionDiff correctly lists changed fields."""
        diff = ToolVersionDiff(
            tool_id="00000000-0000-0000-0000-000000000001",
            old_version=1,
            new_version=2,
            changed_fields=["name", "input_schema"],
        )
        assert "name" in diff.changed_fields
        assert "input_schema" in diff.changed_fields


class TestAPIResponseShapes:
    """Verify API response shapes match expected Pydantic models."""

    def test_health_response_shape(self) -> None:
        """Health response contains required fields."""
        from nexus.api.schemas import HealthResponse

        resp = HealthResponse(status="ok", version="0.1.0")
        assert resp.status == "ok"
        assert resp.version == "0.1.0"

    def test_error_response_shape(self) -> None:
        """Error response contains required fields."""
        from nexus.api.schemas import ErrorResponse

        resp = ErrorResponse(detail="Not found", error_code="NOT_FOUND", request_id="req_123")
        assert resp.error_code == "NOT_FOUND"

    def test_chat_request_validates_message_length(self) -> None:
        """ChatRequest rejects empty messages."""
        import pydantic
        from nexus.api.schemas import ChatRequest

        with pytest.raises(pydantic.ValidationError):
            ChatRequest(message="")

    def test_chat_response_includes_events(self) -> None:
        """ChatResponse properly serializes events list."""
        from nexus.api.schemas import ChatResponse

        resp = ChatResponse(
            session_id="sess_1",
            final_response="Done",
            events=[{"type": "plan_created", "data": {"steps": []}}],
        )
        assert len(resp.events) == 1
        assert resp.events[0]["type"] == "plan_created"

    def test_pagination_consistent(self) -> None:
        """ToolList pagination fields are consistent."""
        from nexus.tools.schemas import ToolList

        lst = ToolList(items=[], total=0, page=1, page_size=20)
        assert lst.page == 1
        assert lst.page_size == 20
        assert lst.total == 0

    def test_session_create_invalid_title(self) -> None:
        """Session schema validation."""
        import pydantic
        from nexus.sessions.schemas import SessionCreate

        with pytest.raises(pydantic.ValidationError):
            SessionCreate(title="a" * 1000)
