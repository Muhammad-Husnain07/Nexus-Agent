"""MCPClient — connects to external MCP servers via JSON-RPC over HTTP.

Supports tool discovery (``tools/list``) and tool execution (``tools/call``)
following the Model Context Protocol specification. Does NOT support Python
code execution.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from nexus.config.settings import get_settings
from nexus.tools.result import ToolResult

logger = structlog.get_logger("nexus.tools.mcp_client")


def _get_mcp_retry_settings() -> tuple[int, float, float]:
    """Return (max_attempts, backoff_base_s, backoff_max_s) from settings or fallback."""
    try:
        s = get_settings().tools
        return s.mcp_retry_max_attempts, s.mcp_retry_backoff_base_s, s.mcp_retry_backoff_max_s
    except Exception:
        return 3, 1.0, 30.0


class _McpRetryPredicate:
    """Retry predicate for MCP transport errors."""

    def __call__(self, exc: BaseException) -> bool:
        return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


def _mcp_retry_policy(max_attempts: int | None = None) -> AsyncRetrying:
    attempts, base_s, max_s = _get_mcp_retry_settings()
    # F7/P1-A (I12): a NON-idempotent MCP tool call is never automatically
    # retried — a transport failure after the request was sent may mean the
    # side effect already fired; retrying duplicates it.
    if max_attempts is not None and max_attempts < 2:
        attempts = 1
    return AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=base_s, max=max_s)
        + wait_random(0, 1),
        retry=retry_if_exception(_McpRetryPredicate()),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


class ToolDefinition(BaseModel):
    """An MCP tool definition discovered from an external server."""

    name: str = Field(description="Tool name")
    description: str = Field(default="", description="Tool description")
    input_schema: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema for tool inputs"
    )


class MCPClient:
    """Client for interacting with external MCP servers over HTTP.

    Maintains a connection pool and supports retry with exponential backoff.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        timeout_s = settings.tools.execution_timeout_s

        if http_client is not None:
            self._client = http_client
        else:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_s),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            )

    async def list_mcp_tools(
        self,
        server_url: str,
        headers: dict[str, str] | None = None,
    ) -> list[ToolDefinition]:
        """Discover available tools from an external MCP server.

        Sends a JSON-RPC ``tools/list`` request to the server.

        Args:
            server_url: Base URL of the MCP server.
            headers: Optional HTTP headers (e.g. auth tokens).

        Returns:
            A list of discovered ``ToolDefinition`` objects.

        Raises:
            httpx.TimeoutException: If the server does not respond in time.
            httpx.TransportError: On connection or transport failures.
        """
        request_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/list",
            "params": {},
        }

        response = await self._request(server_url, payload, headers=headers)
        result = self._parse_jsonrpc_response(response, server_url, "tools/list")
        return [ToolDefinition(**item) for item in result.get("tools", [])]

    async def call_mcp_tool(
        self,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any],
        headers: dict[str, str] | None = None,
        idempotent: bool = False,
    ) -> ToolResult:
        """Execute a tool on an external MCP server.

        Sends a JSON-RPC ``tools/call`` request and returns the result.

        Args:
            server_url: Base URL of the MCP server.
            tool_name: Name of the tool to invoke.
            arguments: Input parameters for the tool.
            headers: Optional HTTP headers (e.g. auth tokens).
            idempotent: F7/P1-A (I12) — False (default) disables the
                automatic transport retry: a non-idempotent operation is
                never retried across outcome uncertainty.

        Returns:
            A ``ToolResult`` summarising the execution outcome.
        """
        tool_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{server_url}/{tool_name}")

        start = time.perf_counter()
        request_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        try:
            response = await self._request(
                server_url, payload, headers=headers, idempotent=idempotent
            )
        except httpx.TimeoutException:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_id=tool_id,
                tool_name=tool_name,
                status="timeout",
                error="MCP tool call timed out",
                duration_ms=duration_ms,
            )
        except httpx.TransportError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return ToolResult(
                tool_id=tool_id,
                tool_name=tool_name,
                status="error",
                error=f"MCP transport error: {exc}",
                duration_ms=duration_ms,
            )

        duration_ms = int((time.perf_counter() - start) * 1000)

        try:
            result = self._parse_jsonrpc_response(response, server_url, "tools/call")
        except ValueError as exc:
            return ToolResult(
                tool_id=tool_id,
                tool_name=tool_name,
                status="error",
                error=str(exc),
                duration_ms=duration_ms,
            )

        content = result.get("content", [])
        is_error = result.get("is_error", False)

        if is_error:
            error_text = content[0].get("text", str(content)) if content else "Unknown MCP error"
            return ToolResult(
                tool_id=tool_id,
                tool_name=tool_name,
                status="error",
                error=error_text,
                duration_ms=duration_ms,
            )

        data = content[0] if content else None
        return ToolResult(
            tool_id=tool_id,
            tool_name=tool_name,
            status="success",
            data=data if isinstance(data, dict) else {"result": data},
            duration_ms=duration_ms,
        )

    async def _request(
        self,
        server_url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        idempotent: bool = False,
    ) -> httpx.Response:
        """Send a JSON-RPC request to the MCP server with retry.

        F7/P1-A (I12): ``idempotent=False`` (the default) disables the
        automatic retry — a non-idempotent operation is never retried
        across outcome uncertainty.
        """
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        retry_policy = _mcp_retry_policy(max_attempts=1 if not idempotent else None)
        response: httpx.Response | None = None

        try:
            async for attempt in retry_policy:
                with attempt:
                    response = await self._client.post(
                        server_url.rstrip("/") + "/",
                        content=json.dumps(payload),
                        headers=req_headers,
                    )
                    response.raise_for_status()
        except Exception:
            if response is not None:
                raise  # Re-raise the last captured exception
            raise

        return response  # type: ignore[return-value]

    @staticmethod
    def _parse_jsonrpc_response(
        response: httpx.Response,
        server_url: str,
        method: str,
    ) -> dict[str, Any]:
        """Validate and extract the result from a JSON-RPC response."""
        try:
            body: dict[str, Any] = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(
                f"MCP server {server_url} returned invalid JSON for {method}: {exc}"
            ) from exc

        if "error" in body and body["error"] is not None:
            err = body["error"]
            msg = err.get("message", str(err))
            raise ValueError(f"MCP server error calling {method}: {msg}")

        if "result" not in body:
            raise ValueError(
                f"MCP server {server_url} response for {method} missing 'result' field"
            )

        return body["result"]

    async def close(self) -> None:
        """Close the underlying ``httpx.AsyncClient``."""
        await self._client.aclose()
