"""MCP server setup — exposes tool registry via FastApiMCP."""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi_mcp import FastApiMCP

from nexus.tools.registry import ToolRegistry

logger = structlog.get_logger("nexus.tools.mcp_server")


def setup_mcp(app: FastAPI, tool_registry: ToolRegistry) -> None:
    """Attach FastApiMCP to the FastAPI application.

    Exposes all API routes as MCP tools under ``/sse``.
    """
    mcp = FastApiMCP(
        app,
        name="Nexus Agent MCP Server",
        description="Model Context Protocol server for Nexus Agent",
    )
    mcp.mount_sse(mount_path="/sse")

    logger.info("mcp.server_setup", mount_path="/sse")
