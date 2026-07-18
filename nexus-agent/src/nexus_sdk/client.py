"""Nexus Agent SDK — typed Python client.

Provides synchronous and async methods for all major API endpoints.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from nexus_sdk.sse import stream_chat_events
from nexus_sdk.types import ApprovalAction, ChatEvent, SessionInfo, ToolSchema


class NexusClient:
    """Typed Python client for the Nexus Agent API.

    Usage::

        client = NexusClient("http://localhost:8000", token="eyJ...")
        tool = await client.register_tool(name="echo", endpoint_url="...")
        session = await client.create_session("My Chat")
        async for event in client.send_message(session.id, "Hello", stream=True):
            print(event.type, event.payload)
    """

    def __init__(self, base_url: str, token: str, timeout_s: int = 30) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._timeout = httpx.Timeout(timeout_s)
        self._client = httpx.AsyncClient(headers=self._headers, timeout=self._timeout)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ── Tools ──────────────────────────────────────────────────────────────

    async def register_tool(self, tool: ToolSchema) -> dict[str, Any]:
        """Register a new tool."""
        resp = await self._client.post(
            f"{self._base_url}/api/v1/tools",
            content=tool.model_dump_json(),
        )
        resp.raise_for_status()
        return resp.json()

    async def list_tools(self, **filters: Any) -> list[dict[str, Any]]:
        """List registered tools with optional filters."""
        resp = await self._client.get(
            f"{self._base_url}/api/v1/tools",
            params={k: v for k, v in filters.items() if v is not None},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", data) if isinstance(data, dict) else data

    async def search_tools(self, query: str, k: int = 10) -> list[dict[str, Any]]:
        """Semantic search for tools."""
        resp = await self._client.get(
            f"{self._base_url}/api/v1/tools/search",
            params={"q": query, "k": k},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_tool(self, tool_id: uuid.UUID) -> dict[str, Any]:
        """Get a single tool by ID."""
        resp = await self._client.get(f"{self._base_url}/api/v1/tools/{tool_id}")
        resp.raise_for_status()
        return resp.json()

    async def delete_tool(self, tool_id: uuid.UUID) -> None:
        """Soft-delete a tool."""
        resp = await self._client.delete(f"{self._base_url}/api/v1/tools/{tool_id}")
        resp.raise_for_status()

    # ── Sessions ───────────────────────────────────────────────────────────

    async def create_session(self, title: str = "New Session") -> SessionInfo:
        """Create a new conversation session."""
        resp = await self._client.post(
            f"{self._base_url}/api/v1/sessions",
            json={"title": title},
        )
        resp.raise_for_status()
        return SessionInfo(**resp.json())

    async def get_session(self, session_id: uuid.UUID) -> SessionInfo:
        """Get session details."""
        resp = await self._client.get(f"{self._base_url}/api/v1/sessions/{session_id}")
        resp.raise_for_status()
        return SessionInfo(**resp.json())

    async def delete_session(self, session_id: uuid.UUID) -> None:
        """Archive a session."""
        resp = await self._client.delete(f"{self._base_url}/api/v1/sessions/{session_id}")
        resp.raise_for_status()

    async def get_messages(
        self, session_id: uuid.UUID, page: int = 1, page_size: int = 50
    ) -> list[dict[str, Any]]:
        """Get message history for a session."""
        resp = await self._client.get(
            f"{self._base_url}/api/v1/sessions/{session_id}/messages",
            params={"page": page, "page_size": page_size},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", data) if isinstance(data, dict) else data

    # ── Chat ───────────────────────────────────────────────────────────────

    async def send_message(
        self,
        session_id: uuid.UUID,
        message: str,
        stream: bool = True,
    ) -> AsyncIterator[ChatEvent] | dict[str, Any]:
        """Send a message to the agent.

        If ``stream=True`` (default), returns an async iterator of ``ChatEvent``.
        If ``stream=False``, returns the full JSON response dict.
        """
        if stream:
            return self._stream_chat(session_id, message)

        resp = await self._client.post(
            f"{self._base_url}/api/v1/sessions/{session_id}/chat",
            json={"message": message, "stream": False},
        )
        resp.raise_for_status()
        return resp.json()

    async def _stream_chat(
        self,
        session_id: uuid.UUID,
        message: str,
    ) -> AsyncIterator[ChatEvent]:
        async for event in stream_chat_events(
            self._base_url,
            str(session_id),
            message,
            self._token,
        ):
            yield event

    # ── Approvals ──────────────────────────────────────────────────────────

    async def get_pending_approvals(self, session_id: uuid.UUID) -> list[dict[str, Any]]:
        """List pending approvals for a session."""
        resp = await self._client.get(
            f"{self._base_url}/api/v1/approvals/pending/{session_id}",
        )
        resp.raise_for_status()
        return resp.json()

    async def decide_approval(
        self,
        approval_id: uuid.UUID,
        decision: ApprovalAction,
    ) -> dict[str, Any]:
        """Make a decision on a pending approval."""
        resp = await self._client.post(
            f"{self._base_url}/api/v1/approvals/{approval_id}/decide",
            content=decision.model_dump_json(exclude_none=True),
        )
        resp.raise_for_status()
        return resp.json()

    # ── Health ─────────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, str]:
        """Check the server's health."""
        resp = await self._client.get(f"{self._base_url}/healthz")
        resp.raise_for_status()
        return resp.json()

    async def readiness_check(self) -> dict[str, str]:
        """Check if the server is ready (DB + Redis connectivity)."""
        resp = await self._client.get(f"{self._base_url}/readyz")
        resp.raise_for_status()
        return resp.json()
