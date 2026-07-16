"""MCP server — exposes the tool registry via the Model Context Protocol.

Uses ``fastapi_mcp.FastApiMCP`` to auto-generate MCP tool definitions
from FastAPI endpoints tagged with ``"mcp"``.
"""

from __future__ import annotations

import json
import uuid

import httpx
import structlog
from fastapi import APIRouter, FastAPI
from fastapi_mcp import FastApiMCP

from nexus.db.base import get_session
from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger("nexus.tools.mcp")


def setup_mcp(app: FastAPI, registry: ToolRegistry) -> None:
    """Attach MCP endpoints to the FastAPI application."""
    mcp_internal = APIRouter(prefix="/_mcp", tags=["mcp"])

    @mcp_internal.get("/tools/list")
    async def mcp_list_tools() -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        async for session in get_session():
            tool_list = await registry.list(session, uuid.UUID(int=0), enabled=True, page_size=500)
            for t in tool_list.items:
                results.append(
                    {
                        "name": t.name,
                        "description": t.description or t.purpose,
                        "input_schema": t.input_schema or {"type": "object", "properties": {}},
                    }
                )
        return results

    @mcp_internal.post("/tools/call")
    async def mcp_call_tool(
        tool_name: str,
        arguments: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        args = arguments or {}
        async for session in get_session():
            tool_list = await registry.list(session, uuid.UUID(int=0), enabled=True, page_size=500)
            tool = next((t for t in tool_list.items if t.name == tool_name), None)
            if tool is None:
                return [{"content": f"Tool '{tool_name}' not found", "is_error": True}]

            headers: dict[str, str] = {}
            if tool.auth_type and tool.auth_type != "none" and tool.auth_ref:
                headers["Authorization"] = f"Bearer {{{tool.auth_type}:{tool.auth_ref}}}"

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    method = tool.http_method.lower()
                    if method == "get":
                        resp = await client.get(
                            tool.endpoint_url,
                            params=args,
                            headers=headers,
                        )
                    else:
                        resp = await client.request(
                            method,
                            tool.endpoint_url,
                            json=args,
                            headers=headers,
                        )
                    resp.raise_for_status()
                    content = json.dumps(resp.json())
                    return [{"content": content, "is_error": False}]
            except Exception as exc:
                return [{"content": str(exc), "is_error": True}]
        return [{"content": "No session available", "is_error": True}]

    app.include_router(mcp_internal)

    FastApiMCP(
        app,
        name="Nexus Tools",
        description="Registered tool catalog for Nexus Agent",
        include_tags=["mcp"],
    )
    logger.info("mcp.server.attached", base_url="/mcp")
