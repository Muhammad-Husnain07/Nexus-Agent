"""Integration tests for the tools API — register, search, MCP flow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from nexus.tools.api import router as tools_router
from nexus.tools.mcp_server import setup_mcp
from nexus.tools.registry import ToolRegistry
from nexus.tools.schemas import ToolRead


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI()
    a.include_router(tools_router)
    registry = ToolRegistry()
    setup_mcp(a, registry)
    a.state.tool_registry = registry

    import uuid

    from nexus.api.depends import _current_tenant
    from nexus.security.rbac import Role, get_current_user

    async def mock_user_with_role() -> tuple[uuid.UUID, Role]:
        return uuid.UUID("00000000-0000-0000-0000-000000000002"), Role.TENANT_ADMIN

    async def mock_tenant() -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-000000000001")

    a.dependency_overrides[_current_tenant] = mock_tenant
    a.dependency_overrides[get_current_user] = mock_user_with_role
    return a


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_tool_read() -> ToolRead:
    now = datetime.now(UTC)
    return ToolRead(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="calculator",
        description="Performs basic arithmetic",
        purpose="Add, subtract, multiply, divide",
        endpoint_url="https://api.example.com/calc",
        http_method="POST",
        auth_type="none",
        auth_ref="",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
                "op": {"type": "string", "enum": ["add", "sub", "mul", "div"]},
            },
            "required": ["a", "b", "op"],
        },
        output_schema={},
        validation_rules={},
        examples=[],
        tags=["math", "calculator"],
        category="utilities",
        requires_approval=False,
        risk_level="low",
        enabled=True,
        version=1,
        created_at=now,
        updated_at=now,
    )


class TestToolApi:
    @patch("nexus.tools.api.ToolRegistry.register")
    @patch("nexus.tools.api.ToolRegistry.list")
    async def test_register_and_list(
        self,
        mock_list: AsyncMock,
        mock_register: AsyncMock,
        client: AsyncClient,
        sample_tool_read: ToolRead,
    ) -> None:
        mock_register.return_value = sample_tool_read

        body = sample_tool_read.model_dump(
            exclude={
                "id",
                "tenant_id",
                "created_at",
                "updated_at",
                "version",
            }
        )
        resp = await client.post(
            "/api/v1/tools",
            json={"tool_data": body},
        )
        assert resp.status_code in (200, 201)

    @patch("nexus.tools.api.ToolRegistry.search_semantic")
    async def test_search(
        self,
        mock_search: AsyncMock,
        client: AsyncClient,
    ) -> None:
        mock_search.return_value = []

        resp = await client.get("/api/v1/tools/search", params={"q": "math"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @patch("nexus.tools.api.ToolRegistry.get")
    async def test_get_not_found(
        self,
        mock_get: AsyncMock,
        client: AsyncClient,
    ) -> None:
        mock_get.return_value = None
        resp = await client.get(f"/api/v1/tools/{uuid.uuid4()}")
        assert resp.status_code == 404

    @patch("nexus.tools.api.ToolRegistry.get")
    async def test_test_endpoint(
        self,
        mock_get: AsyncMock,
        client: AsyncClient,
        sample_tool_read: ToolRead,
    ) -> None:
        mock_get.return_value = sample_tool_read
        resp = await client.post(
            f"/api/v1/tools/{uuid.uuid4()}/test",
            json={"a": 1, "b": 2, "op": "add"},
        )
        assert resp.status_code == 200

    @patch("nexus.tools.api.ToolRegistry.list")
    async def test_mcp_tools_list(
        self,
        mock_list: AsyncMock,
        client: AsyncClient,
        sample_tool_read: ToolRead,
    ) -> None:
        tool_list = MagicMock()
        tool_list.items = [sample_tool_read]
        mock_list.return_value = tool_list

        resp = await client.get("/_mcp/tools/list")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
