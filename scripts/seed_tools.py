"""Register demo tools with embeddings via ToolRegistry.

Run this AFTER the server is started (needs LLM for embeddings):
  uv run python scripts/seed_tools.py
"""

from __future__ import annotations

import asyncio
import json
import uuid

import asyncpg

from nexus.db.base import async_session
from nexus.llm.client import LLMClient
from nexus.tools.registry import EMBEDDING_MODEL
from nexus.tools.schemas import ToolCreate

TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")

TOOLS = [
    ToolCreate(
        name="echo",
        description="Echoes back the user input. Useful for testing connectivity and basic responses.",
        purpose="Test the tool execution pipeline and verify the agent can call tools.",
        endpoint_url="https://httpbin.org/post",
        http_method="POST",
        input_schema={
            "type": "object",
            "properties": {"msg": {"type": "string", "description": "Message to echo back"}},
            "required": ["msg"],
        },
        output_schema={"type": "object", "properties": {"echo": {"type": "string"}}},
        tags=["test", "utility"],
        category="utilities",
        risk_level="low",
        examples=[{"user_prompt": "Say hello back to me", "expected_tool": "echo", "sample_input": {"msg": "Hello"}, "sample_output": {"echo": "Hello"}}],
    ),
    ToolCreate(
        name="create_draft",
        description="Create a draft article with a title and category. Returns the draft ID and title.",
        purpose="Content creation - use when the user asks to write, create, or draft an article.",
        endpoint_url="https://httpbin.org/post",
        http_method="POST",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the draft article"},
                "category": {"type": "string", "description": "Category for the draft (e.g. Tech, News, Blog)"},
            },
            "required": ["title"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Unique draft ID"},
                "title": {"type": "string", "description": "Title of the created draft"},
            },
        },
        tags=["content", "writing", "draft"],
        category="writing",
        risk_level="low",
        requires_approval=False,
        examples=[{"user_prompt": "Create a draft titled Hello World in Tech", "expected_tool": "create_draft", "sample_input": {"title": "Hello World", "category": "Tech"}, "sample_output": {"id": "draft-123", "title": "Hello World"}}],
    ),
    ToolCreate(
        name="publish_draft",
        description="Publish a draft article by its draft ID. Returns the published URL.",
        purpose="Publication - use when the user asks to publish, release, or make a draft live.",
        endpoint_url="https://httpbin.org/post",
        http_method="POST",
        input_schema={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "The ID of the draft to publish"},
            },
            "required": ["draft_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL of the published article"},
            },
        },
        tags=["content", "publishing", "approval"],
        category="publishing",
        risk_level="high",
        requires_approval=True,
        idempotent=True,
        examples=[{"user_prompt": "Publish draft draft-123", "expected_tool": "publish_draft", "sample_input": {"draft_id": "draft-123"}, "sample_output": {"url": "https://example.com/articles/123"}}],
    ),
]


def _embedding_text(name: str, description: str, purpose: str, tags: list[str]) -> str:
    tag_str = ",".join(sorted(tags)) if tags else ""
    return f"{name}: {description}. {purpose}. tags: {tag_str}"


async def seed() -> None:
    """Register tools via ToolRegistry (generates embeddings)."""
    llm = LLMClient()
    from sqlalchemy import select, text
    from nexus.db.models.tool import Tool

    async with async_session() as session:
        # Clear old tools
        from sqlalchemy import delete
        await session.execute(delete(Tool).where(Tool.tenant_id == TENANT_ID))
        await session.commit()

        for tool_data in TOOLS:
            # Generate embedding
            text_for_embed = _embedding_text(tool_data.name, tool_data.description, tool_data.purpose, tool_data.tags)
            embedding = None
            try:
                embeddings = await llm.embed(EMBEDDING_MODEL, [text_for_embed])
                if embeddings and embeddings[0]:
                    embedding = embeddings[0]
            except Exception as e:
                print(f"  Embedding failed for {tool_data.name}: {e}")

            # Insert via direct asyncpg connection to avoid SQLAlchemy issues
            tool_id = uuid.uuid4()
            conn = await asyncpg.connect("postgresql://nexus:nexus@localhost:5433/nexus")
            try:
                await conn.execute("""
                    INSERT INTO tool (id, tenant_id, name, description, purpose, endpoint_url,
                        http_method, auth_type, input_schema, output_schema, tags, category,
                        requires_approval, risk_level, enabled, version, embedding)
                    VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, 'none',
                        $8::jsonb, $9::jsonb, $10::text[], $11,
                        $12, $13, true, 1, $14::vector(768))
                """,
                    tool_id, TENANT_ID, tool_data.name, tool_data.description,
                    tool_data.purpose, tool_data.endpoint_url, tool_data.http_method,
                    json.dumps(tool_data.input_schema), json.dumps(tool_data.output_schema),
                    tool_data.tags, tool_data.category,
                    tool_data.requires_approval, tool_data.risk_level,
                    json.dumps(embedding) if embedding else None,
                )
            finally:
                await conn.close()
            print(f"  Registered: {tool_data.name} (embedding: {'yes' if embedding else 'no'})")

        await session.commit()
    print("Seed complete!")


if __name__ == "__main__":
    asyncio.run(seed())
