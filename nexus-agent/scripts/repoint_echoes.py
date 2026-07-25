"""Re-register echo tools to point at the local proxy server instead of httpbin.org."""
import asyncio
import httpx

PROXY = "http://localhost:8081"
BASE = "http://localhost:8000/api/v1"

TOOLS = [
    {
        "name": "echo_delete",
        "endpoint_url": f"{PROXY}/bookmarks/{{bookmark_id}}",
        "http_method": "DELETE",
    },
    {
        "name": "echo_patch",
        "endpoint_url": f"{PROXY}/bookmarks/{{bookmark_id}}",
        "http_method": "PATCH",
    },
    {
        "name": "echo_post",
        "endpoint_url": f"{PROXY}/bookmarks",
        "http_method": "POST",
    },
    {
        "name": "echo_put",
        "endpoint_url": f"{PROXY}/bookmarks/{{bookmark_id}}",
        "http_method": "PUT",
    },
]


async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.get(f"{BASE}/tools")
        existing = {t["name"]: t for t in resp.json().get("items", [])}

        for tool in TOOLS:
            name = tool["name"]
            if name in existing:
                tid = existing[name]["id"]
                up = await c.put(f"{BASE}/tools/{tid}", json={
                    "endpoint_url": tool["endpoint_url"],
                    "http_method": tool["http_method"],
                })
                if up.status_code == 200:
                    print(f"  ✅ {name:25s} → {tool['endpoint_url']}")
                else:
                    print(f"  ❌ {name:25s} — {up.status_code}: {up.text[:100]}")
            else:
                print(f"  ❌ {name:25s} — not found")

asyncio.run(main())
