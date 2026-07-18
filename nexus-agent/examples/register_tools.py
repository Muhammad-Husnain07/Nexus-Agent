"""Register Content Studio endpoints as Nexus Agent tools.

Run after starting Nexus Agent (port 8000) and the demo app (port 8080).

Usage:
    python examples/register_tools.py
"""

from __future__ import annotations

import httpx

API_BASE = "http://localhost:8000/api/v1"
DEMO_BASE = "http://127.0.0.1:8081"
TOKEN = "<your-nexus-jwt-or-api-key>"  # get from login endpoint

TOOLS = [
    # ── Listing endpoints ──────────────────────────────────────────────
    {
        "name": "list_articles",
        "description": "Lists all articles in the Content Studio. Optionally filters by category, status, or tag.",
        "purpose": "Use when the user wants to see, browse, search, or find articles.",
        "endpoint_url": f"{DEMO_BASE}/articles",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Filter by category name (Tech, Business, Science)", "examples": ["Tech"]},
                "status": {"type": "string", "description": "Filter by status (draft, published)", "examples": ["published"]},
                "tag": {"type": "string", "description": "Filter by tag name (AI, ML, Cloud, etc.)", "examples": ["AI"]},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "articles": {"type": "array", "items": {"type": "object"}},
                "total": {"type": "integer"},
            },
        },
        "tags": ["content", "articles", "read"],
        "category": "content",
        "requires_approval": False,
        "risk_level": "low",
        "examples": [
            {"user_prompt": "Show me all articles", "sample_input": {}, "sample_output": {"articles": [], "total": 0}},
            {"user_prompt": "List published articles in Tech", "sample_input": {"category": "Tech", "status": "published"}, "sample_output": {"articles": [], "total": 0}},
        ],
    },
    {
        "name": "get_article",
        "description": "Gets a single article by its ID. Returns full article details including title, content, category, tags, and status.",
        "purpose": "Use when the user wants to read or view a specific article.",
        "endpoint_url": f"{DEMO_BASE}/articles/{{article_id}}",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "The article ID (e.g. a0000001)", "examples": ["a0000001"]},
            },
            "required": ["article_id"],
        },
        "output_schema": {"type": "object", "properties": {"article": {"type": "object"}}},
        "tags": ["content", "articles", "read"],
        "category": "content",
        "requires_approval": False,
        "risk_level": "low",
    },
    {
        "name": "list_categories",
        "description": "Lists all available categories (Tech, Business, Science).",
        "purpose": "Use when the user asks about categories or what categories exist.",
        "endpoint_url": f"{DEMO_BASE}/categories",
        "http_method": "GET",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {"categories": {"type": "array"}}},
        "tags": ["content", "categories", "read"],
        "category": "content",
        "requires_approval": False,
        "risk_level": "low",
    },
    {
        "name": "list_tags",
        "description": "Lists all available tags (AI, ML, Cloud, SaaS, Research).",
        "purpose": "Use when the user asks about tags or available keywords.",
        "endpoint_url": f"{DEMO_BASE}/tags",
        "http_method": "GET",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {"tags": {"type": "array"}}},
        "tags": ["content", "tags", "read"],
        "category": "content",
        "requires_approval": False,
        "risk_level": "low",
    },
    # ── Write endpoints ────────────────────────────────────────────────
    {
        "name": "create_article",
        "description": "Creates a new article draft with a title, content, optional category, and optional tags.",
        "purpose": "Use when the user wants to write, create, or draft a new article or blog post.",
        "endpoint_url": f"{DEMO_BASE}/articles",
        "http_method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Article title (max 200 chars)", "examples": ["AI Trends in 2026"]},
                "content": {"type": "string", "description": "Article body content", "examples": ["Artificial intelligence is ..."]},
                "category": {"type": "string", "description": "Category name (optional, defaults to 'general')", "examples": ["Tech"]},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "List of tag names", "examples": [["AI", "ML"]]},
            },
            "required": ["title", "content"],
        },
        "output_schema": {"type": "object", "properties": {"article": {"type": "object"}}},
        "tags": ["content", "articles", "write"],
        "category": "content",
        "requires_approval": False,
        "risk_level": "low",
        "examples": [
            {
                "user_prompt": "Write a new article about cloud computing",
                "sample_input": {"title": "Cloud Computing Guide", "content": "Cloud computing enables...", "tags": ["Cloud"]},
                "sample_output": {"article": {"id": "abc123", "title": "Cloud Computing Guide", "status": "draft"}},
            }
        ],
    },
    {
        "name": "update_article",
        "description": "Updates an existing article's title, content, category, or tags. Only provided fields are changed.",
        "purpose": "Use when the user wants to edit, modify, or change an article.",
        "endpoint_url": f"{DEMO_BASE}/articles/{{article_id}}",
        "http_method": "PUT",
        "input_schema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "The article ID to update", "examples": ["a0000001"]},
                "title": {"type": "string", "description": "New title (optional)", "examples": ["Updated Title"]},
                "content": {"type": "string", "description": "New content (optional)", "examples": ["Updated content..."]},
                "category": {"type": "string", "description": "New category (optional)", "examples": ["Business"]},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "New tags (optional)", "examples": [["AI"]]},
            },
            "required": ["article_id"],
        },
        "output_schema": {"type": "object", "properties": {"article": {"type": "object"}}},
        "tags": ["content", "articles", "write"],
        "category": "content",
        "requires_approval": False,
        "risk_level": "low",
    },
    # ── Destructive / approval-gated endpoints ─────────────────────────
    {
        "name": "publish_article",
        "description": "Publishes a draft article, changing its status from 'draft' to 'published'. Cannot be undone.",
        "purpose": "Use when the user wants to publish, release, or make an article live.",
        "endpoint_url": f"{DEMO_BASE}/articles/{{article_id}}/publish",
        "http_method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "The article ID to publish", "examples": ["a0000001"]},
            },
            "required": ["article_id"],
        },
        "output_schema": {"type": "object", "properties": {"article": {"type": "object"}}},
        "tags": ["content", "articles", "publish"],
        "category": "content",
        "requires_approval": True,
        "risk_level": "medium",
    },
    {
        "name": "delete_article",
        "description": "Permanently deletes an article. This action cannot be reversed.",
        "purpose": "Use ONLY when the user explicitly asks to delete or remove an article.",
        "endpoint_url": f"{DEMO_BASE}/articles/{{article_id}}",
        "http_method": "DELETE",
        "input_schema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "The article ID to delete", "examples": ["a0000001"]},
            },
            "required": ["article_id"],
        },
        "output_schema": {"type": "object", "properties": {"deleted": {"type": "boolean"}}},
        "tags": ["content", "articles", "admin"],
        "category": "content",
        "requires_approval": True,
        "risk_level": "high",
    },
    # ── Utility endpoints ──────────────────────────────────────────────
    {
        "name": "preview_article",
        "description": "Generates an HTML preview of an article by its ID. Returns rendered HTML and metadata.",
        "purpose": "Use when the user wants to preview, view a draft, or see how an article looks before publishing.",
        "endpoint_url": f"{DEMO_BASE}/articles/{{article_id}}/preview",
        "http_method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "The article ID to preview", "examples": ["a0000001"]},
            },
            "required": ["article_id"],
        },
        "output_schema": {"type": "object", "properties": {"html": {"type": "string"}, "title": {"type": "string"}}},
        "tags": ["content", "articles", "preview"],
        "category": "content",
        "requires_approval": False,
        "risk_level": "low",
    },
]


async def register_all() -> None:
    async with httpx.AsyncClient() as client:
        for tool in TOOLS:
            resp = await client.post(
                f"{API_BASE}/tools",
                headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
                json=tool,
            )
            if resp.status_code == 201:
                print(f"  ✓ {tool['name']}")
            else:
                print(f"  ✗ {tool['name']}: {resp.status_code} {resp.text}")
        print(f"\nRegistered {len(TOOLS)} tools.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(register_all())
