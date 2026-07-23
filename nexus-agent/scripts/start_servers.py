"""Start proxy + Nexus servers and run comprehensive real-time tests."""

import asyncio
import logging
import os
import subprocess
import sys
import time
import uuid

import httpx

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger(__name__)

NEXUS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(NEXUS_DIR, ".venv", "Scripts", "python.exe")


async def wait_for(url: str, timeout: int = 90) -> bool:
    import httpx
    start = time.time()
    async with httpx.AsyncClient(timeout=5) as c:
        while time.time() - start < timeout:
            try:
                r = await c.get(url)
                if r.status_code < 500:
                    return True
            except Exception:
                pass
            await asyncio.sleep(2)
    return False


async def test_health(c):
    r = await c.get("http://localhost:8000/healthz")
    assert r.status_code == 200
    log.info("[OK] Health check")


async def test_ready(c):
    r = await c.get("http://localhost:8000/readyz")
    assert r.status_code in (200, 503)
    log.info(f"[OK] Readiness: {r.status_code}")


async def test_list_tools(c):
    r = await c.get("http://localhost:8000/api/v1/tools")
    assert r.status_code == 200
    items = r.json().get("items", [])
    log.info(f"[OK] Tools listed: {len(items)} tools")
    for t in items[:5]:
        log.info(f"     {t['name']:<25} {t.get('http_method','?'):<6} {t.get('risk_level','?'):<6}")


async def test_semantic_search(c):
    r = await c.get("http://localhost:8000/api/v1/tools/search?q=search+web&k=5")
    assert r.status_code == 200
    results = r.json()
    assert len(results) > 0
    log.info(f"[OK] Semantic search: {len(results)} results")


async def test_create_session(c):
    r = await c.post("http://localhost:8000/api/v1/sessions", json={"title": "Real-time Test"})
    assert r.status_code in (200, 201), f"Session create: {r.status_code}"
    sid = r.json()["id"]
    log.info(f"[OK] Session created: {sid[:8]}...")
    return sid


async def test_chat_json(c, sid: str, message: str, label: str, timeout_s: int = 300):
    """Send a chat message and get JSON response."""
    log.info(f"\n--- {label} ---")
    log.info(f"     Message: {message}")
    t0 = time.time()
    try:
        r = await c.post(
            f"http://localhost:8000/api/v1/sessions/{sid}/chat",
            json={"message": message, "stream": False},
            timeout=timeout_s,
        )
        elapsed = time.time() - t0
        if r.status_code == 200:
            data = r.json()
            fr = data.get("final_response", "")
            events = data.get("events", [])
            event_types = [e.get("type", "?") for e in events]
            log.info(f"     Status: {r.status_code} | Time: {elapsed:.1f}s")
            log.info(f"     Events: {', '.join(event_types[:8])}" + ("..." if len(event_types) > 8 else ""))
            clean_fr = fr.encode('ascii', 'replace').decode('ascii')[:200]
            log.info(f"     Response: {clean_fr}")
            return True, fr, event_types
        else:
            log.info(f"     [FAIL] Status: {r.status_code}")
            return False, "", []
    except Exception as e:
        elapsed = time.time() - t0
        log.info(f"     [TIMEOUT] after {elapsed:.0f}s: {str(e)[:80]}")
        return False, "", []


async def test_greeting(c):
    sid = str(uuid.uuid4())
    ok, fr, _ = await test_chat_json(c, sid, "Hello! How are you?", "Greeting Test")
    assert ok
    log.info(f"[OK] Greeting handled")


async def test_meta(c):
    sid = str(uuid.uuid4())
    ok, fr, _ = await test_chat_json(c, sid, "What can you do? What tools do you have?", "Meta Question")
    assert ok
    log.info(f"[OK] Meta question answered")


async def test_multi_turn(c):
    """Test multi-turn conversation with context retention."""
    sid = str(uuid.uuid4())
    
    # Turn 1: Set a fact
    ok1, _, events1 = await test_chat_json(c, sid, "My name is Alice and I love AI technology", "Multi-turn - Turn 1")
    
    # Turn 2: Ask about it (agent should remember)
    ok2, fr2, events2 = await test_chat_json(c, sid, "What is my name and what do I love?", "Multi-turn - Turn 2")
    
    if ok2 and ("Alice" in fr2 or "alice" in fr2.lower()):
        log.info("[OK] Multi-turn: agent remembered Alice")
    else:
        log.info("[WARN] Multi-turn: agent may not have recalled the name")
    
    # Turn 3: Summary
    ok3, fr3, _ = await test_chat_json(c, sid, "Summarize our conversation so far", "Multi-turn - Turn 3")
    
    return sid


async def test_chat_stream(c, sid: str):
    """Test SSE streaming endpoint."""
    log.info(f"\n--- SSE Streaming Test ---")
    t0 = time.time()
    events = []
    async with c.stream(
        "POST",
        f"http://localhost:8000/api/v1/sessions/{sid}/chat",
        json={"message": "Search the web for the latest AI developments", "stream": True},
        timeout=300,
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
    
    elapsed = time.time() - t0
    log.info(f"     Duration: {elapsed:.1f}s")
    log.info(f"     Events ({len(events)}): {', '.join(events[:10])}" + ("..." if len(events) > 10 else ""))
    
    if "plan_created" in events:
        log.info("[OK] SSE: plan_created event received")
    if "final_response" in events:
        log.info("[OK] SSE: final_response event received")
    if "done" in events:
        log.info("[OK] SSE: done event received")
    
    return events


async def test_session_messages(c, sid: str):
    r = await c.get(f"http://localhost:8000/api/v1/sessions/{sid}/messages", timeout=30)
    assert r.status_code == 200, f"Messages: {r.status_code}"
    msgs = r.json().get("items", [])
    log.info(f"[OK] Messages: {len(msgs)} messages in session")
    for m in msgs:
        content_preview = str(m.get("content", ""))[:60]
        log.info(f"     {m['role']:<10}: {content_preview}")


async def test_session_list(c):
    r = await c.get("http://localhost:8000/api/v1/sessions")
    assert r.status_code == 200
    sessions = r.json().get("items", [])
    log.info(f"[OK] Sessions listed: {len(sessions)} total")


async def main():
    # Wait for servers
    log.info("Waiting for servers...")
    nexus_ok = await wait_for("http://localhost:8000/healthz", timeout=120)
    proxy_ok = await wait_for("http://localhost:8081/search?q=test", timeout=30)
    
    if not nexus_ok:
        log.error("Nexus server not available!")
        return
    log.info(f"  Nexus: {'[OK]' if nexus_ok else '[FAIL]'}")
    log.info(f"  Proxy: {'[OK]' if proxy_ok else '[FAIL]'}")
    
    log.info("\n" + "=" * 60)
    log.info("COMPREHENSIVE REAL-TIME TESTS")
    log.info("=" * 60 + "\n")
    
    async with httpx.AsyncClient(timeout=30) as c:
        # 1. Infrastructure
        await test_health(c)
        await test_ready(c)
        
        # 2. Tools
        await test_list_tools(c)
        await test_semantic_search(c)
        
        # 3. Sessions
        sid = await test_create_session(c)
        await test_session_list(c)
        
        # 4. Chat (non-tool)
        await test_greeting(c)
        await test_meta(c)
        
        # 5. Multi-turn conversation
        session_id = await test_multi_turn(c)
        
        # 6. Chat with tool calling (web search)
        sid2 = str(uuid.uuid4())
        await test_chat_json(c, sid2, "Search the web for the latest developments in artificial intelligence", "Tool: Web Search")
        
        # 7. SSE streaming
        await test_chat_stream(c, sid2)
        
        # 8. Messages
        await test_session_messages(c, session_id)
        await test_session_messages(c, sid2)
    
    log.info("\n" + "=" * 60)
    log.info("ALL REAL-TIME TESTS COMPLETED")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
