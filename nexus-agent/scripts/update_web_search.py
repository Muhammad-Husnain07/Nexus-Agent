"""Update web_search tool endpoint to point at running proxy server."""
import httpx
import asyncio

BASE = "http://localhost:8000/api/v1"

async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        # List tools
        resp = await c.get(f"{BASE}/tools")
        tools = resp.json().get("items", [])
        web = [t for t in tools if t["name"] == "web_search"]
        if not web:
            print("web_search tool not found!")
            return
        tool = web[0]
        tid = tool["id"]
        print(f"Current: {tool['endpoint_url']}")
        # Update
        up = await c.put(f"{BASE}/tools/{tid}", json={
            "endpoint_url": "http://localhost:8081/search",
        })
        print(f"Update: {up.status_code}")
        if up.status_code != 200:
            print(up.text[:300])
        # Verify
        resp = await c.get(f"{BASE}/tools/{tid}")
        t = resp.json()
        print(f"New endpoint: {t['endpoint_url']}")

asyncio.run(main())
