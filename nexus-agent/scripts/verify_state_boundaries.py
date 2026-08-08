"""Verify workflow state survives EVERY turn boundary (DB checkpoint dump)."""
import asyncio
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from nexus.config.settings import get_settings

BASE = "http://localhost:8000/api/v1"

async def dump_wf(engine, sid, label):
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT checkpoint_id FROM checkpoints WHERE thread_id=:t ORDER BY checkpoint_id DESC LIMIT 1"
        ), {"t": sid})
        row = r.fetchone()
        if not row:
            print(f"[{label}] NO CHECKPOINT")
            return
        cp = row[0]
        r = await conn.execute(text(
            "SELECT channel, blob::text FROM checkpoint_writes WHERE thread_id=:t AND checkpoint_id=:c "
            "AND channel IN ('_active_workflow_id','_workflow_collected','_workflow_captured') ORDER BY channel"
        ), {"t": sid, "c": cp})
        rows = r.fetchall()
        wf = {ch: bl[:40] for ch, bl in rows}
        print(f"[{label}] wf={wf}")

async def turn(client, sid, msg):
    events, tools = [], []
    async with client.stream("POST", f"{BASE}/sessions/{sid}/chat",
            json={"message": msg, "stream": True}, timeout=240) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
            elif line.startswith("data: "):
                import json
                try:
                    d = json.loads(line[6:])
                    if events and events[-1] == "tool_call_completed":
                        p = d.get("payload", {}) or {}
                        tools.append((p.get("tool_name"), p.get("status")))
                except Exception:
                    pass
    return events, tools

async def main():
    engine = create_async_engine(get_settings().database.url)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{BASE}/sessions", json={"title": "State Verify"})
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
            events, tools = await turn(client, sid, msg)
            notable = [e for e in events if e != "node_completed"]
            print(f"T{i}: {notable} tools={tools}")
            await dump_wf(engine, sid, f"after T{i}")
            if "approval_required" in events:
                ar = await client.post(f"{BASE}/sessions/{sid}/approve", timeout=300)
                print(f"  approve: HTTP {ar.status_code}")
                await asyncio.sleep(5)
                await dump_wf(engine, sid, f"after T{i} approve")
    await engine.dispose()

asyncio.run(main())
