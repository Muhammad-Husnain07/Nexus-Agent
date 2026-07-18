"""Integration tests: HTTP methods, auth, timeouts, retry, sandbox, rate limiting,
schema validation, and MCP server integration.

Uses testcontainers for DB/Redis (via ``integration/conftest.py``) and ``respx``
for HTTP mocking.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

from nexus.config.settings import get_settings
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.mcp_client import MCPClient
from nexus.tools.schemas import ToolRead

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def _test_env() -> None:
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"
    os.environ["NEXUS_TOOLS__SANDBOX_ENABLED"] = "true"
    get_settings.cache_clear()


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        agent_run_id=uuid.uuid4(),
    )


def _make_tool(**overrides: object) -> ToolRead:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "name": "test_tool",
        "description": "A test tool",
        "purpose": "Testing",
        "tool_type": "http_api",
        "endpoint_url": "http://localhost:9999/action",
        "mcp_server_url": "",
        "http_method": "POST",
        "auth_type": "none",
        "auth_ref": "",
        "input_schema": {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
        "output_schema": {"type": "object", "properties": {"echo": {"type": "string"}}},
        "validation_rules": {},
        "examples": [],
        "tags": [],
        "category": "general",
        "requires_approval": False,
        "risk_level": "low",
        "enabled": True,
        "version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return ToolRead(**base)


# ---------------------------------------------------------------------------
# HTTP Method Tests
# ---------------------------------------------------------------------------


class TestHttpMethods:
    """Verify GET / POST / PUT / DELETE all work correctly."""

    async def test_get_request(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        tool = _make_tool(http_method="GET", endpoint_url="http://localhost:9999/search")
        respx_mock.get(tool.endpoint_url).respond(200, json={"results": ["a", "b"]})
        executor = ToolExecutor()
        result = await executor.execute(tool, {"q": "test"}, context, AsyncMock())
        assert result.status == "success"
        assert result.data == {"results": ["a", "b"]}

    async def test_post_request(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        tool = _make_tool(http_method="POST", endpoint_url="http://localhost:9999/create")
        respx_mock.post(tool.endpoint_url).respond(201, json={"id": "42", "status": "created"})
        executor = ToolExecutor()
        result = await executor.execute(tool, {"name": "new-item"}, context, AsyncMock())
        assert result.status == "success"
        assert result.data == {"id": "42", "status": "created"}

    async def test_put_request(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        tool = _make_tool(http_method="PUT", endpoint_url="http://localhost:9999/update")
        respx_mock.put(tool.endpoint_url).respond(200, json={"updated": True})
        executor = ToolExecutor()
        result = await executor.execute(tool, {"id": "1"}, context, AsyncMock())
        assert result.status == "success"
        assert result.data == {"updated": True}

    async def test_delete_request(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        tool = _make_tool(http_method="DELETE", endpoint_url="http://localhost:9999/delete/1")
        respx_mock.delete(tool.endpoint_url).respond(204)
        executor = ToolExecutor()
        result = await executor.execute(tool, {}, context, AsyncMock())
        assert result.status == "success"
        assert result.http_status == 204


# ---------------------------------------------------------------------------
# Authentication Tests
# ---------------------------------------------------------------------------


class TestAuthMethods:
    """Verify bearer, basic, and api_key auth headers are sent."""

    async def _exec_and_capture(
        self, tool: ToolRead, respx_mock: respx.MockRouter,
    ) -> dict[str, str]:
        route = respx_mock.request(tool.http_method, tool.endpoint_url).respond(200, json={"ok": True})
        executor = ToolExecutor()
        await executor.execute(tool, {"msg": "hello"}, ExecutionContext(
            tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), session_id=uuid.uuid4(),
        ), AsyncMock())
        return dict(route.calls.last.request.headers)

    async def test_bearer_auth(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        os.environ["MY_BEARER_TOKEN"] = "tok_abc123"
        tool = _make_tool(auth_type="bearer", auth_ref="env:MY_BEARER_TOKEN")
        headers = await self._exec_and_capture(tool, respx_mock)
        assert headers.get("authorization") == "Bearer tok_abc123"
        os.environ.pop("MY_BEARER_TOKEN", None)

    async def test_basic_auth(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        import base64
        os.environ["MY_BASIC_CRED"] = base64.b64encode(b"user:pass").decode()
        tool = _make_tool(auth_type="basic", auth_ref="env:MY_BASIC_CRED")
        headers = await self._exec_and_capture(tool, respx_mock)
        assert "Basic " in headers.get("authorization", "")
        os.environ.pop("MY_BASIC_CRED", None)

    async def test_api_key_auth(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        os.environ["MY_API_KEY"] = "key_secret123"
        tool = _make_tool(auth_type="api_key", auth_ref="env:MY_API_KEY")
        headers = await self._exec_and_capture(tool, respx_mock)
        assert headers.get("x-api-key") == "key_secret123"
        os.environ.pop("MY_API_KEY", None)


# ---------------------------------------------------------------------------
# Timeout Handling
# ---------------------------------------------------------------------------


class TestTimeouts:
    """Verify tool execution returns timeout status."""

    async def test_request_timeout(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        tool = _make_tool(endpoint_url="http://localhost:9999/slow")
        respx_mock.post(tool.endpoint_url).mock(side_effect=httpx.TimeoutException("Timeout", request=MagicMock()))
        executor = ToolExecutor()
        result = await executor.execute(tool, {"msg": "hello"}, context, AsyncMock())
        assert result.status == "timeout"


# ---------------------------------------------------------------------------
# Retry Logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """Verify tenacity retry on 5xx and 429."""

    async def test_retry_on_503_then_success(
        self, context: ExecutionContext, respx_mock: respx.MockRouter,
    ) -> None:
        tool = _make_tool(endpoint_url="http://localhost:9999/flaky")
        route = respx_mock.post(tool.endpoint_url).mock(
            side_effect=[
                httpx.HTTPStatusError("503", request=MagicMock(), response=MagicMock(status_code=503)),
                httpx.Response(200, json={"status": "ok"}),
            ],
        )
        executor = ToolExecutor()
        result = await executor.execute(tool, {"msg": "retry"}, context, AsyncMock())
        assert result.status == "success"
        assert route.call_count == 2

    async def test_max_retries_exhausted(
        self, context: ExecutionContext, respx_mock: respx.MockRouter,
    ) -> None:
        tool = _make_tool(endpoint_url="http://localhost:9999/always-down")
        route = respx_mock.post(tool.endpoint_url).respond(503)
        executor = ToolExecutor()
        result = await executor.execute(tool, {"msg": "fail"}, context, AsyncMock())
        assert result.status == "error"
        assert route.call_count >= 1


# ---------------------------------------------------------------------------
# Sandbox Host Whitelist
# ---------------------------------------------------------------------------


class TestSandboxWhitelist:
    """Verify sandbox blocks disallowed hosts."""

    async def test_blocked_host_returns_error(self, context: ExecutionContext) -> None:
        tool = _make_tool(endpoint_url="http://evil.com/api")
        from nexus.config.settings import get_settings as _gs
        _gs.cache_clear()
        executor = ToolExecutor()
        result = await executor.execute(tool, {"msg": "hack"}, context, AsyncMock())
        assert result.status == "error"
        assert "Host" in (result.error or "")

    async def test_allowed_host_succeeds(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        tool = _make_tool(endpoint_url="https://api.example.com/action")
        respx_mock.post(tool.endpoint_url).respond(200, json={"ok": True})
        executor = ToolExecutor()
        result = await executor.execute(tool, {"msg": "hello"}, context, AsyncMock())
        assert result.status == "success"


# ---------------------------------------------------------------------------
# Schema Validation
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """Verify input/output schema validation."""

    async def test_valid_input_passes(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        tool = _make_tool(
            input_schema={"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
            endpoint_url="http://localhost:9999/valid",
        )
        respx_mock.post(tool.endpoint_url).respond(200, json={"echo": "hello"})
        executor = ToolExecutor()
        result = await executor.execute(tool, {"msg": "hello"}, context, AsyncMock())
        assert result.status == "success"

    async def test_missing_required_field_rejected(self, context: ExecutionContext) -> None:
        tool = _make_tool(
            input_schema={"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
        )
        executor = ToolExecutor()
        result = await executor.execute(tool, {}, context, AsyncMock())
        assert result.status == "validation_error"

    async def test_output_validation_soft_fail(self, context: ExecutionContext, respx_mock: respx.MockRouter) -> None:
        tool = _make_tool(
            output_schema={"type": "object", "properties": {"echo": {"type": "string"}}, "required": ["echo"]},
            endpoint_url="http://localhost:9999/bad-output",
        )
        respx_mock.post(tool.endpoint_url).respond(200, json={"wrong_key": "value"})
        executor = ToolExecutor()
        result = await executor.execute(tool, {"msg": "hello"}, context, AsyncMock())
        assert result.status == "validation_error"


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Verify per-tool rate limiting via Redis token bucket."""

    async def test_rate_limit_hit_returns_error(
        self, context: ExecutionContext, respx_mock: respx.MockRouter,
    ) -> None:
        tool = _make_tool(
            rate_limit_per_minute=1,
            endpoint_url="http://localhost:9999/rl-test",
        )
        respx_mock.post(tool.endpoint_url).respond(200, json={"ok": True})
        executor = ToolExecutor()

        # First call succeeds
        r1 = await executor.execute(tool, {"msg": "first"}, context, AsyncMock())
        assert r1.status == "success"

        # Second call should be rate limited
        r2 = await executor.execute(tool, {"msg": "second"}, context, AsyncMock())
        assert r2.status == "rate_limited"


# ---------------------------------------------------------------------------
# MCP Server Integration
# ---------------------------------------------------------------------------


class TestMcpIntegration:
    """Verify MCP client can call external MCP servers via JSON-RPC."""

    async def test_mcp_tool_call_success(self, respx_mock: respx.MockRouter) -> None:
        server_url = "http://mcp-test.local"
        respx_mock.post(server_url.rstrip("/") + "/").respond(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "any",
                "result": {
                    "content": [{"type": "text", "text": "Hello from MCP"}],
                    "is_error": False,
                },
            },
        )
        client = MCPClient()
        result = await client.call_mcp_tool(server_url, "greet", {"name": "world"})
        assert result.status == "success"
        assert result.data is not None

    async def test_mcp_tool_call_error(self, respx_mock: respx.MockRouter) -> None:
        server_url = "http://mcp-test.local"
        respx_mock.post(server_url.rstrip("/") + "/").respond(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "any",
                "result": {
                    "content": [{"text": "Tool not found"}],
                    "is_error": True,
                },
            },
        )
        client = MCPClient()
        result = await client.call_mcp_tool(server_url, "unknown_tool", {})
        assert result.status == "error"

    async def test_mcp_connection_error(self, respx_mock: respx.MockRouter) -> None:
        server_url = "http://mcp-unreachable.local"
        respx_mock.post(server_url.rstrip("/") + "/").mock(
            side_effect=httpx.ConnectError("Connection refused"),
        )
        client = MCPClient()
        result = await client.call_mcp_tool(server_url, "test", {})
        assert result.status == "error"

    async def test_mcp_list_tools(self, respx_mock: respx.MockRouter) -> None:
        server_url = "http://mcp-test.local"
        respx_mock.post(server_url.rstrip("/") + "/").respond(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "any",
                "result": {
                    "tools": [
                        {"name": "greet", "description": "Says hello", "input_schema": {}},
                        {"name": "echo", "description": "Echoes input", "input_schema": {}},
                    ],
                },
            },
        )
        client = MCPClient()
        tools = await client.list_mcp_tools(server_url)
        assert len(tools) == 2
        assert tools[0].name == "greet"
        assert tools[1].name == "echo"
