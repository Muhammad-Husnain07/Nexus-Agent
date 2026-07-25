"""Update echo tools' input schemas to require bookmark_id for URL template substitution."""
import asyncio
import httpx

BASE_URL = "http://localhost:8000/api/v1"

UPDATES = {
    "echo_delete": {
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to delete"},
            },
            "required": ["bookmark_id"],
        },
    },
    "echo_patch": {
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "title": {"type": "string", "description": "New title"},
            },
            "required": ["bookmark_id"],
        },
    },
    "echo_put": {
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "url": {"type": "string", "description": "New URL"},
                "title": {"type": "string", "description": "New title"},
            },
            "required": ["bookmark_id"],
        },
    },
    "echo_post": {
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL"},
                "title": {"type": "string", "description": "Title"},
            },
            "required": ["url", "title"],
        },
    },
}


async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.get(f"{BASE_URL}/tools")
        existing = {t["name"]: t for t in resp.json().get("items", [])}

        for name, update in UPDATES.items():
            if name in existing:
                tid = existing[name]["id"]
                up = await c.put(f"{BASE_URL}/tools/{tid}", json=update)
                if up.status_code == 200:
                    print(f"  ✅ {name:25s} schema updated")
                else:
                    print(f"  ❌ {name:25s} — {up.status_code}: {up.text[:100]}")
            else:
                print(f"  ❌ {name:25s} — not found")

asyncio.run(main())
