"""Unit tests for the _resolve_placeholders function."""

from __future__ import annotations

from nexus.agent.nodes.execute_step import _resolve_placeholders


def test_resolves_from_gathered():
    """${name} resolves from gathered_requirements."""
    result = _resolve_placeholders(
        {"msg": "Hello ${name}"},
        {"name": "Alice"},
        [],
    )
    assert result["msg"] == "Hello Alice"


def test_resolves_user_email():
    """${user.email} resolves from user_context."""
    result = _resolve_placeholders(
        {"to": "${user.email}"},
        {},
        [],
        user_context={"email": "alice@example.com"},
    )
    assert result["to"] == "alice@example.com"


def test_resolves_user_id():
    """${user.id} resolves from user_context."""
    result = _resolve_placeholders(
        {"created_by": "${user.id}"},
        {},
        [],
        user_context={"id": "user-123"},
    )
    assert result["created_by"] == "user-123"


def test_user_email_without_context_returns_literal():
    """${user.email} without user_context remains literal."""
    result = _resolve_placeholders(
        {"to": "${user.email}"},
        {},
        [],
    )
    assert result["to"] == "${user.email}"


def test_resolves_tool_result_field():
    """${create_draft.id} resolves from tool result data."""
    result = _resolve_placeholders(
        {"draft_id": "${create_draft.id}"},
        {},
        [
            {
                "tool_name": "create_draft",
                "data": {"id": "draft-42", "title": "My Draft"},
                "status": "success",
            }
        ],
    )
    assert result["draft_id"] == "draft-42"


def test_tool_result_field_not_found_returns_literal():
    """${tool.unknown_field} remains literal when not found."""
    result = _resolve_placeholders(
        {"val": "${echo.missing}"},
        {},
        [{"tool_name": "echo", "data": {"present": "yes"}}],
    )
    assert result["val"] == "${echo.missing}"


def test_unknown_placeholder_returns_literal():
    """${unknown.key} remains literal."""
    result = _resolve_placeholders(
        {"val": "${unknown.key}"},
        {},
        [],
    )
    assert result["val"] == "${unknown.key}"


def test_no_placeholders():
    """Input without placeholders passes through unchanged."""
    result = _resolve_placeholders(
        {"name": "Alice", "count": 42},
        {},
        [],
    )
    assert result["name"] == "Alice"
    assert result["count"] == 42


def test_nested_dict_resolves():
    """Placeholders in nested dict values are resolved."""
    result = _resolve_placeholders(
        {"nested": {"msg": "Hello ${name}", "fixed": "world"}},
        {"name": "Alice"},
        [],
    )
    assert result["nested"]["msg"] == "Hello Alice"
    assert result["nested"]["fixed"] == "world"


def test_no_double_brace_artifacts():
    """No double-brace artifacts in output."""
    result = _resolve_placeholders(
        {"a": "${user.email}", "b": "${unknown}", "c": "hello"},
        {},
        [],
    )
    for key, val in result.items():
        assert "${{" not in str(val), key


def test_gathered_overrides_tool_result():
    """gathered_requirements takes priority over tool results."""
    result = _resolve_placeholders(
        {"val": "${name}"},
        {"name": "from_gathered"},
        [{"tool_name": "echo", "data": {"name": "from_tool"}}],
    )
    assert result["val"] == "from_gathered"


def test_multiple_placeholders_in_single_string():
    """Multiple ${...} in one string are all resolved."""
    result = _resolve_placeholders(
        {"msg": "${greeting}, ${name}!"},
        {"greeting": "Hello", "name": "Bob"},
        [],
    )
    assert result["msg"] == "Hello, Bob!"
