"""Quickstart example — register a tool and chat with the agent."""

from __future__ import annotations

import asyncio

from nexus_sdk import NexusClient
from nexus_sdk.types import ToolSchema


async def main() -> None:
    # Configure these for your Nexus Agent instance
    BASE_URL = "http://localhost:8000"
    TOKEN = "<your-jwt-or-api-key>"

    client = NexusClient(BASE_URL, token=TOKEN)

    # Step 1: Register an echo tool
    print("Registering tool...")
    tool = await client.register_tool(
        ToolSchema(
            name="echo",
            description="Echoes back the input for testing",
            purpose="Test tool execution",
            endpoint_url="https://httpbin.org/post",
            http_method="POST",
            input_schema={
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
            output_schema={
                "type": "object",
                "properties": {"echo": {"type": "string"}},
            },
            tags=["test"],
            category="utilities",
            risk_level="low",
        )
    )
    tool_id = tool.get("id", "unknown")
    print(f"  Registered: {tool_id}")

    # Step 2: Create a session
    print("Creating session...")
    session = await client.create_session("Quickstart Demo")
    print(f"  Session: {session.id}")

    # Step 3: Send a message (non-streaming)
    print("Sending message (non-streaming)...")
    result = await client.send_message(session.id, "Say hello back!", stream=False)
    if isinstance(result, dict):
        final = result.get("final_response", "No response")
        print(f"  Agent: {final}")
    else:
        async for event in result:
            print(f"  [{event.type}] {event.payload}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
