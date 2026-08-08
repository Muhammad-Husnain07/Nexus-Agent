"""Verify: scan ALL checkpoint writes for workflow fields; detect null overwrites."""
import asyncio
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nexus.config.settings import get_settings

BASE = "http://localhost:8000/api/v1"
SESSION = None

async def scan(engine, sid, label):
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT checkpoint_id, channel, blob::text FROM checkpoint_writes "
            "WHERE thread_id=:t AND channel IN ('_active_workflow_id','_workflow_collected','_workflow_captured') "
            "ORDER BY checkpoint_id DESC LIMIT 12"
        ), {"t": sid})
        rows = r.fetchall()
        wf = []
        nulls = 0
        for row in rows:
            blob = row[2]
            is_null = blob in (None, "", "\\x", "\\x00")
            if row[1] == "_active_workflow_id" and is_null:
                nulls += 1
            wf.append(f"{row[1][:18]}={blob[:28] if not is_null else 'NULL'}")
        print(f"[{label}] nulls={nulls} latest_writes={len(rows)}")
        for w in wf[:12]:
            print(f"    {w}")

async def turn(client, sid, msg):
    events = []
    async with client.stream("POST", f"{BASE}/sessions/{sid}/chat",
            json={"message": msg, "stream": True}, timeout=240) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
    return events

async def main():
    engine = create_async_engine(get_settings().database.url)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE}/sessions", json={"title": "State Scan"})
        sid = r.json()["id"]
        print(f"Session: {sid}")
        turns = [
            "Build me a dashboard for ATM failures",
            "Use the banking_db datasource",
            "Let's use the atm_failures table",
            "Show me error_code and amount",
            "Looks good, create the dashboard",
            "Finalize it",
        ]
        for i, msg in enumerate(turns, 1):
            events = await turn(client, sid, msg)
            notable = [e for e in events if e != "node_completed"]
            print(f"T{i}: {notable}")
            await scan(engine, sid, f"after T{i}")
            if "approval_required" in events:
                ar = await client.post(f"{BASE}/sessions/{sid}/approve", timeout=300)
                print(f"  approve: HTTP {ar.status_code}")
                await asyncio.sleep(4)
                await scan(engine, sid, f"after T{i} approve")
    await engine.dispose()

asyncio.run(main())
