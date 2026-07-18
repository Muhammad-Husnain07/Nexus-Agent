"""SSE streaming client for the Nexus Agent API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from nexus_sdk.types import ChatEvent


async def stream_chat_events(
    base_url: str,
    session_id: str,
    message: str,
    token: str,
) -> AsyncIterator[ChatEvent]:
    """Stream chat events via SSE from the Nexus Agent API.

    Args:
        base_url: The Nexus Agent server URL (e.g. http://localhost:8000).
        session_id: The conversation session UUID.
        message: The user message to send.
        token: JWT or API key for authentication.

    Yields:
        ``ChatEvent`` instances as the agent processes the message.
    """
    url = f"{base_url}/api/v1/sessions/{session_id}/chat"

    async with httpx.AsyncClient() as client, client.stream(
        "POST",
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"message": message, "stream": True},
    ) as response:
        response.raise_for_status()
        buffer = ""
        current_event_type: str | None = None

        async for chunk in response.aiter_bytes():
            buffer += chunk.decode()
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if line.startswith("event: "):
                    current_event_type = line[7:]
                elif line.startswith("data: "):
                    raw = json.loads(line[6:])
                    yield ChatEvent(
                        type=raw.get("type", current_event_type or "unknown"),
                        ts=raw.get("ts", ""),
                        payload=raw.get("payload", raw),
                    )
                elif line.startswith(": "):
                    pass  # keep-alive comment, skip
