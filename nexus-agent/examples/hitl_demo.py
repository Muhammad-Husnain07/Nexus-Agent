"""HITL approval flow example — register a high-risk tool and approve/reject."""

from __future__ import annotations

import asyncio

from nexus_sdk import NexusClient
from nexus_sdk.types import ApprovalAction, ToolSchema


async def main() -> None:
    BASE_URL = "http://localhost:8000"
    TOKEN = "<your-jwt-or-api-key>"

    client = NexusClient(BASE_URL, token=TOKEN)

    # Step 1: Register a high-risk tool that requires approval
    print("Registering high-risk tool...")
    tool = await client.register_tool(
        ToolSchema(
            name="delete_user",
            description="Deletes a user account permanently. Requires approval.",
            purpose="Delete user accounts from the system",
            endpoint_url="https://api.example.com/users/{user_id}",
            http_method="DELETE",
            auth_type="bearer",
            auth_ref="env:ADMIN_API_KEY",
            input_schema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "The user ID to delete"}
                },
                "required": ["user_id"],
            },
            requires_approval=True,
            risk_level="high",
            tags=["admin", "users"],
            category="admin",
        )
    )
    print(f"  Registered: {tool.get('id')}")

    # Step 2: Create session and send a destructive request
    session = await client.create_session("HITL Demo")
    print(f"  Session: {session.id}")
    print("  Sending destructive request...")

    async for event in client.send_message(
        session.id,
        "Delete user account abc-123",
        stream=True,
    ):
        print(f"  [{event.type}] {event.payload}")

        if event.type == "approval_required":
            print("\n  === TOOL REQUIRES APPROVAL ===")
            print(f"  Tool: {event.payload.get('tool_call', {}).get('name')}")
            print(f"  Inputs: {event.payload.get('tool_call', {}).get('inputs')}")
            print(f"  Risk: {event.payload.get('risk_level')}")

            # Approve the tool call
            decision = ApprovalAction(action="approve", comment="Approved for testing")
            pending = await client.get_pending_approvals(session.id)
            if pending:
                approval_id = pending[0]["id"]
                result = await client.decide_approval(approval_id, decision)
                print(f"  Decision result: {result}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
