"""Re-register missing tools with working endpoints.

- web_search → Wikipedia API (free, no API key)
- create_bookmark → httpbin.org/post (echo testing)
- update_bookmark → httpbin.org/put
- patch_bookmark → httpbin.org/patch
- delete_bookmark → httpbin.org/delete
"""

import asyncio
import httpx

BASE_URL = "http://localhost:8000/api/v1"

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web for information on any topic. Returns title, URL, and snippet for each result.",
        "purpose": "Use when the user asks to search, look up, find, or research something online.",
        "endpoint_url": "https://en.wikipedia.org/w/api.php",
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
                "query": {"type": "object"},
                "results": {"type": "array"},
                "result_count": {"type": "integer"},
            },
        },
        "tags": ["search", "web", "reference"],
        "category": "search",
        "risk_level": "low",
    },
    {
        "name": "create_bookmark",
        "description": "Save a web bookmark with URL, title, and optional tags.",
        "purpose": "Use when the user asks to save, bookmark, or store a web link.",
        "endpoint_url": "https://httpbin.org/post",
        "http_method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri", "description": "Bookmark URL"},
                "title": {"type": "string", "description": "Bookmark title"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
            },
            "required": ["url", "title"],
        },
        "tags": ["bookmarks", "write", "create"],
        "category": "bookmarks",
        "risk_level": "low",
    },
    {
        "name": "update_bookmark",
        "description": "Replace ALL fields of an existing bookmark.",
        "purpose": "Use when the user wants to completely overwrite a bookmark's data.",
        "endpoint_url": "https://httpbin.org/put",
        "http_method": "PUT",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "url": {"type": "string", "format": "uri", "description": "New URL"},
                "title": {"type": "string", "description": "New title"},
            },
            "required": ["bookmark_id", "url", "title"],
        },
        "tags": ["bookmarks", "write", "update"],
        "category": "bookmarks",
        "risk_level": "low",
    },
    {
        "name": "patch_bookmark",
        "description": "Partially update a bookmark — only send the fields that changed.",
        "purpose": "Use for partial updates to bookmark fields.",
        "endpoint_url": "https://httpbin.org/patch",
        "http_method": "PATCH",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "title": {"type": "string", "description": "New title (optional)"},
            },
            "required": ["bookmark_id"],
        },
        "tags": ["bookmarks", "write", "patch"],
        "category": "bookmarks",
        "risk_level": "low",
    },
    {
        "name": "delete_bookmark",
        "description": "Permanently delete a bookmark. CANNOT be undone.",
        "purpose": "Use ONLY when the user explicitly asks to delete or remove a bookmark.",
        "endpoint_url": "https://httpbin.org/delete",
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
        "risk_level": "low",
    },
]


async def register_all():
    async with httpx.AsyncClient(timeout=30) as client:
        for tool in TOOLS:
            try:
                resp = await client.post(f"{BASE_URL}/tools", json=tool)
                if resp.status_code == 201:
                    data = resp.json()
                    print(f"  ✅ {tool['name']:25s} — id={data['id'][:8]}... v{data.get('version', 1)}")
                elif resp.status_code == 409:
                    print(f"  ⚠️  {tool['name']:25s} — already exists")
                else:
                    print(f"  ❌ {tool['name']:25s} — {resp.status_code}: {resp.text[:80]}")
            except Exception as exc:
                print(f"  💥 {tool['name']:25s} — {exc}")


async def verify():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/tools")
        if resp.status_code == 200:
            tools = resp.json().get("items", [])
            print(f"\nTotal tools: {len(tools)}")
            for t in tools:
                print(f"  {t['name']:30s} {t.get('http_method', '?'):7s} {t.get('endpoint_url', '')[:50]}")


async def cleanup_old():
    """Hard-delete old disabled tools so we can re-register."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/tools?enabled=false&page_size=100")
        if resp.status_code == 200:
            old_tools = resp.json().get("items", [])
            deleted_names = set()
            for t in old_tools:
                if t.get("name") in {tool["name"] for tool in TOOLS}:
                    await client.delete(f"{BASE_URL}/tools/{t['id']}")
                    deleted_names.add(t["name"])
            if deleted_names:
                print(f"  Cleaned up {len(deleted_names)} old tools: {', '.join(sorted(deleted_names))}")


async def main():
    print("Re-registering missing tools...\n")
    await cleanup_old()
    await register_all()
    await verify()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
