"""Test streaming chat to find the issue."""
import httpx, json, sys
from jose import jwt
from datetime import datetime, timedelta, timezone

t = jwt.encode({'sub':'00000000-0000-0000-0000-000000000001','role':'developer','iss':'nexus-agent','iat':datetime.now(timezone.utc),'exp':datetime.now(timezone.utc)+timedelta(days=30),'type':'access','tid':'11111111-1111-4111-8111-111111111111'},'change-me-to-a-strong-random-secret',algorithm='HS256')
h = {"Authorization":f"Bearer {t}","X-Tenant-ID":"11111111-1111-4111-8111-111111111111","Content-Type":"application/json"}

async def main():
    c = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    
    # Create session
    r = await c.post("http://localhost:8000/api/v1/sessions", headers=h, json={"title":"test"})
    sid = r.json()["id"]
    print(f"Session: {sid}", flush=True)
    
    # Stream chat
    async with c.stream("POST", f"http://localhost:8000/api/v1/sessions/{sid}/chat",
        headers=h, json={"message":"List articles in Tech","stream":True}) as resp:
        print(f"Status: {resp.status_code}", flush=True)
        buffer = ""
        async for chunk in resp.aiter_bytes():
            text = chunk.decode()
            for line in text.split("\n"):
                if line.startswith("data: "):
                    print(f"  EVENT: {line[6:][:100]}", flush=True)
                elif line.startswith("event: "):
                    print(f"  TYPE: {line[7:]}", flush=True)
    await c.aclose()

import asyncio
asyncio.run(main())
