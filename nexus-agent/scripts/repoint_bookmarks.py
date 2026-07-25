"""Re-register bookmark tools to point at the local proxy server (port 8081) instead of httpbin.org."""
import asyncio
import httpx

PROXY = "http://localhost:8081"
BASE = "http://localhost:8000/api/v1"

TOOLS = [
    {
        "name": "create_bookmark",
        "endpoint_url": f"{PROXY}/bookmarks",
        "http_method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Bookmark URL"},
                "title": {"type": "string", "description": "Bookmark title"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags"},
                "description": {"type": "string", "description": "Optional description"},
            },
            "required": ["url", "title"],
        },
    },
    {
        "name": "update_bookmark",
        "endpoint_url": f"{PROXY}/bookmarks/{{bookmark_id}}",
        "http_method": "PUT",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "url": {"type": "string", "description": "New URL"},
                "title": {"type": "string", "description": "New title"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "required": ["bookmark_id", "url", "title"],
        },
    },
    {
        "name": "patch_bookmark",
        "endpoint_url": f"{PROXY}/bookmarks/{{bookmark_id}}",
        "http_method": "PATCH",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "title": {"type": "string", "description": "New title"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "required": ["bookmark_id"],
        },
    },
    {
        "name": "delete_bookmark",
        "endpoint_url": f"{PROXY}/bookmarks/{{bookmark_id}}",
        "http_method": "DELETE",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to delete"},
            },
            "required": ["bookmark_id"],
        },
    },
]


async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        # Get current tool list
        resp = await c.get(f"{BASE}/tools")
        existing = {t["name"]: t for t in resp.json().get("items", [])}

        for tool in TOOLS:
            name = tool["name"]
            if name in existing:
                tid = existing[name]["id"]
                # Update with new endpoint_url
                up = await c.put(f"{BASE}/tools/{tid}", json={
                    "endpoint_url": tool["endpoint_url"],
                    "http_method": tool["http_method"],
                    "input_schema": tool["input_schema"],
                })
                if up.status_code == 200:
                    print(f"  ✅ {name:25s} → {tool['endpoint_url']}")
                else:
                    print(f"  ❌ {name:25s} — {up.status_code}: {up.text[:100]}")
            else:
                print(f"  ❌ {name:25s} — not found")

asyncio.run(main())
