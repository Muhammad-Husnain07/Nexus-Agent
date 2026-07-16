"""Unit tests for tools Pydantic schemas."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from nexus.tools.schemas import ToolCreate, ToolExample, ToolRead, ToolUpdate


class TestToolExample:
    def test_minimal(self) -> None:
        ex = ToolExample(user_prompt="hello", expected_tool="greet")
        assert ex.user_prompt == "hello"
        assert ex.expected_tool == "greet"
        assert ex.sample_input == {}
        assert ex.sample_output == {}


class TestToolCreate:
    def test_minimal(self) -> None:
        t = ToolCreate(name="my-tool")
        assert t.name == "my-tool"
        assert t.description == ""
        assert t.http_method == "GET"
        assert t.auth_type == "none"
        assert t.tags == []
        assert t.examples == []

    def test_with_examples(self) -> None:
        ex = ToolExample(user_prompt="ping", expected_tool="my-tool")
        t = ToolCreate(name="my-tool", examples=[ex])
        assert len(t.examples) == 1

    def test_name_required(self) -> None:
        with pytest.raises(ValidationError):
            ToolCreate()  # type: ignore[call-arg]


class TestToolRead:
    def test_from_attributes(self) -> None:
        now = "2026-07-16T00:00:00+00:00"
        data = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "name": "test-tool",
            "description": "A test tool",
            "purpose": "Testing",
            "endpoint_url": "",
            "http_method": "POST",
            "auth_type": "bearer",
            "auth_ref": "",
            "input_schema": {"type": "object"},
            "output_schema": {},
            "validation_rules": {},
            "examples": [],
            "tags": ["test"],
            "category": "general",
            "requires_approval": False,
            "risk_level": "low",
            "enabled": True,
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        t = ToolRead(**data)
        assert t.name == "test-tool"
        assert t.version == 1


class TestToolUpdate:
    def test_all_optional(self) -> None:
        t = ToolUpdate()
        assert t.name is None

    def test_partial(self) -> None:
        t = ToolUpdate(description="new desc")
        assert t.description == "new desc"
        assert t.name is None
