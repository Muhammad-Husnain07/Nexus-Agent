"""Register web search tools (GET/POST/PUT/PATCH/DELETE) with the Nexus Agent API.

Usage::
    uv run python scripts/register_web_tools.py
"""

import asyncio
import sys

import httpx

BASE_URL = "http://localhost:8000/api/v1"

TOOLS = [
    # ── GET: Web Search ──────────────────────────────────────────────────────
    {
        "name": "web_search",
        "description": "Search the web for information on any topic. Returns title, URL, and snippet for each result.",
        "purpose": "Use when the user asks to search, look up, find, or research something online.",
        "endpoint_url": "http://localhost:8081/search",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (1-20)", "default": 5},
            },
            "required": ["q"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "results": {"type": "array", "items": {"type": "object"}},
                "result_count": {"type": "integer"},
            },
        },
        "tags": ["search", "web", "read"],
        "category": "search",
        "risk_level": "low",
        "requires_approval": False,
    },
    # ── POST: Create Bookmark ────────────────────────────────────────────────
    {
        "name": "create_bookmark",
        "description": "Save a web bookmark with URL, title, and optional tags.",
        "purpose": "Use when the user asks to save, bookmark, or store a web link.",
        "endpoint_url": "http://localhost:8081/bookmarks",
        "http_method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri", "description": "Bookmark URL"},
                "title": {"type": "string", "description": "Bookmark title"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                "description": {"type": "string", "description": "Optional description"},
            },
            "required": ["url", "title"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"}, "url": {"type": "string"}, "title": {"type": "string"},
                "created_at": {"type": "string"},
            },
        },
        "tags": ["bookmarks", "write", "create"],
        "category": "bookmarks",
        "risk_level": "low",
        "requires_approval": False,
    },
    # ── PUT: Full Update Bookmark ────────────────────────────────────────────
    {
        "name": "update_bookmark",
        "description": "Replace ALL fields of an existing bookmark. Requires all fields.",
        "purpose": "Use when the user wants to completely overwrite a bookmark's data.",
        "endpoint_url": "http://localhost:8081/bookmarks/{bookmark_id}",
        "http_method": "PUT",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "url": {"type": "string", "format": "uri", "description": "New URL"},
                "title": {"type": "string", "description": "New title"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "required": ["bookmark_id", "url", "title"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"}, "url": {"type": "string"}, "title": {"type": "string"},
                "updated_at": {"type": "string"},
            },
        },
        "tags": ["bookmarks", "write", "update"],
        "category": "bookmarks",
        "risk_level": "low",
        "requires_approval": False,
    },
    # ── PATCH: Partial Update Bookmark ───────────────────────────────────────
    {
        "name": "patch_bookmark",
        "description": "Partially update a bookmark — only send the fields that changed.",
        "purpose": "Use when the user wants to update only specific fields of a bookmark.",
        "endpoint_url": "http://localhost:8081/bookmarks/{bookmark_id}",
        "http_method": "PATCH",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "title": {"type": "string", "description": "New title (optional)"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "required": ["bookmark_id"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"}, "title": {"type": "string"}, "tags": {"type": "array"},
                "updated_at": {"type": "string"},
            },
        },
        "tags": ["bookmarks", "write", "patch"],
        "category": "bookmarks",
        "risk_level": "low",
        "requires_approval": False,
    },
    # ── DELETE: Delete Bookmark ──────────────────────────────────────────────
    {
        "name": "delete_bookmark",
        "description": "Permanently delete a bookmark. CANNOT be undone.",
        "purpose": "Use ONLY when the user explicitly asks to delete or remove a bookmark.",
        "endpoint_url": "http://localhost:8081/bookmarks/{bookmark_id}",
        "http_method": "DELETE",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to delete"},
            },
            "required": ["bookmark_id"],
        },
        "tags": ["bookmarks", "admin", "delete"],
        "category": "bookmarks",
        "risk_level": "high",
        "requires_approval": True,
    },
]


async def register_all():
    async with httpx.AsyncClient(timeout=30) as client:
        for tool in TOOLS:
            try:
                resp = await client.post(f"{BASE_URL}/tools", json=tool)
                if resp.status_code == 201:
                    data = resp.json()
                    print(f'  ✅ {tool["name"]:25s} — id={data["id"][:8]}... v{data.get("version", 1)}')
                elif resp.status_code == 409:
                    print(f'  ⚠️  {tool["name"]:25s} — already exists (409)')
                else:
                    err = resp.text[:200]
                    print(f'  ❌ {tool["name"]:25s} — {resp.status_code}: {err}')
            except Exception as exc:
                print(f'  💥 {tool["name"]:25s} — {exc}')


async def verify_registration():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/tools")
        if resp.status_code == 200:
            tools = resp.json().get("items", [])
            print(f"\n📋 Registered tools ({len(tools)}):")
            for t in tools:
                print(f"   {t['name']:25s} {t.get('http_method', '?'):7s} {t.get('risk_level', '?'):8s} "
                      f"approval={t.get('requires_approval', False)}")
        else:
            print(f"\n❌ Failed to list tools: {resp.status_code}")


async def main():
    print("🔧 Registering web search tools...\n")
    await register_all()
    await verify_registration()
    print("\n✅ Done. Start chatting via POST /api/v1/sessions/{id}/chat")


if __name__ == "__main__":
    asyncio.run(main())
