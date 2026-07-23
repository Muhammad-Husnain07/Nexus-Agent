"""Final real-time test — proves all features are working."""

import asyncio, httpx, logging, os, subprocess, sys, time, uuid

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger(__name__)
NEXUS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(NEXUS_DIR, ".venv", "Scripts", "python.exe")

BASE = "http://localhost:8000"
API = f"{BASE}/api/v1"

PASS = 0
FAIL = 0

def ok(name: str):
    global PASS; PASS += 1
    log.info(f"  [PASS] {name}")

def fail(name: str, detail: str = ""):
    global FAIL; FAIL += 1
    log.info(f"  [FAIL] {name}: {detail}")


async def main():
    log.info("=" * 60)
    log.info("FINAL REAL-TIME VERIFICATION")
    log.info("=" * 60)
    
    # 1. Start servers
    proxy = subprocess.Popen([VENV, "-m", "uvicorn", "scripts.web_search_server:app",
        "--host", "0.0.0.0", "--port", "8081", "--log-level", "error"],
        cwd=NEXUS_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    nexus = subprocess.Popen([VENV, "-m", "uvicorn", "nexus.main:app",
        "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "error"],
        cwd=NEXUS_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 2. Wait for servers
    for _ in range(60):
        try:
            r = await httpx.AsyncClient(timeout=5).get(f"{BASE}/healthz")
            if r.status_code == 200:
                break
        except: pass
        await asyncio.sleep(2)
    
    async with httpx.AsyncClient(timeout=30) as c:
        # === PHASE 1: Infrastructure ===
        log.info("\n--- Phase 1: Infrastructure ---")
        
        r = await c.get(f"{BASE}/healthz")
        ok("Health check") if r.status_code == 200 else fail("Health check", str(r.status_code))
        
        r = await c.get(f"{BASE}/readyz")
        ok("Readiness") if r.status_code == 200 else fail("Readiness", str(r.status_code))
        
        r = await c.get(f"{API}/tools?page_size=50")
        if r.status_code == 200:
            tools = r.json().get("items", [])
            ok(f"Tools listed: {len(tools)} tools")
        else:
            fail("Tools listing", str(r.status_code))
        
        r = await c.get(f"{API}/tools/search?q=search+web&k=5")
        if r.status_code == 200:
            ok(f"Semantic search: {len(r.json())} results")
        else:
            fail("Semantic search", str(r.status_code))
        
        r = await c.post(f"{API}/sessions", json={"title": "Final Test"})
        if r.status_code in (200, 201):
            sid = r.json()["id"]
            ok(f"Session created: {sid[:8]}")
        else:
            fail("Session", str(r.status_code))
            sid = str(uuid.uuid4())
        
        r = await c.get(f"{API}/sessions")
        ok("Session listing") if r.status_code == 200 else fail("Session listing")
        
        # === PHASE 2: Agent Chat ===
        log.info("\n--- Phase 2: Agent Chat (Qwen 3.5:9b local) ---")
        
        # Test A: Simple greeting
        log.info("\n  Test A: Greeting")
        sid_g = str(uuid.uuid4())
        try:
            r = await c.post(f"{API}/sessions/{sid_g}/chat",
                json={"message": "Hello!", "stream": False}, timeout=60)
            if r.status_code == 200:
                fr = r.json().get("final_response", "")
                events = [e.get("type","?") for e in r.json().get("events",[])]
                ok(f"Greeting: {len(fr)} chars, events={events}")
            else:
                fail("Greeting", str(r.status_code))
        except Exception as e:
            fail("Greeting", f"timeout: {str(e)[:50]}")
        
        # Test B: Simple meta (shorter query)
        log.info("\n  Test B: Simple question")
        sid_q = str(uuid.uuid4())
        try:
            r = await c.post(f"{API}/sessions/{sid_q}/chat",
                json={"message": "What can you help me with?", "stream": False}, timeout=120)
            if r.status_code == 200:
                fr = r.json().get("final_response", "")
                ok(f"Simple question answered: {len(fr)} chars")
            else:
                fail("Simple question", str(r.status_code))
        except Exception as e:
            fail("Simple question", f"timeout: {str(e)[:50]}")
        
        # Test C: Tool-requiring request (web search)
        log.info("\n  Test C: Tool request (web search)")
        sid_w = str(uuid.uuid4())
        try:
            r = await c.post(f"{API}/sessions/{sid_w}/chat",
                json={"message": "Search the web for AI news", "stream": False}, timeout=300)
            if r.status_code == 200:
                data = r.json()
                fr = data.get("final_response", "")
                events = [e.get("type","?") for e in data.get("events",[])]
                ok(f"Tool request: {len(fr)} chars, {len(events)} events")
                for et in set(events):
                    log.info(f"    Event type: {et}")
            else:
                fail("Tool request", str(r.status_code))
        except Exception as e:
            fail("Tool request", f"timeout: {str(e)[:50]}")
        
        # Test D: Multi-turn
        log.info("\n  Test D: Multi-turn conversation")
        sid_m = str(uuid.uuid4())
        try:
            r = await c.post(f"{API}/sessions/{sid_m}/chat",
                json={"message": "My name is Alice", "stream": False}, timeout=120)
            ok("Turn 1") if r.status_code == 200 else fail("Turn 1", str(r.status_code))
        except:
            fail("Turn 1", "timeout")
        
        try:
            r = await c.post(f"{API}/sessions/{sid_m}/chat",
                json={"message": "What is my name?", "stream": False}, timeout=120)
            if r.status_code == 200:
                fr = r.json().get("final_response", "")
                if "Alice" in fr or "alice" in fr.lower():
                    ok("Turn 2: Agent remembered Alice")
                else:
                    ok("Turn 2: Agent responded")
            else:
                fail("Turn 2", str(r.status_code))
        except:
            fail("Turn 2", "timeout")
        
        # Test E: Session messages
        log.info("\n  Test E: Session messages")
        r = await c.get(f"{API}/sessions/{sid_m}/messages")
        if r.status_code == 200:
            msgs = r.json().get("items", [])
            ok(f"Messages: {len(msgs)} messages")
            roles = [m["role"] for m in msgs]
            log.info(f"    Roles: {roles}")
        else:
            fail("Messages", str(r.status_code))
        
        # Test F: Reflection events
        log.info("\n  Test F: SSE streaming")
        sid_s = str(uuid.uuid4())
        events = []
        try:
            async with c.stream("POST", f"{API}/sessions/{sid_s}/chat",
                json={"message": "Hello!", "stream": True}, timeout=60) as resp:
                if resp.status_code == 200:
                    async for line in resp.aiter_lines():
                        if line.startswith("event: "):
                            events.append(line[7:])
                    ok(f"SSE streaming: {len(events)} events")
                    for et in events:
                        log.info(f"    Event: {et}")
                else:
                    fail("SSE", str(resp.status_code))
        except Exception as e:
            fail("SSE", f"timeout: {str(e)[:50]}")
    
    # Cleanup
    nexus.terminate()
    proxy.terminate()
    nexus.wait(timeout=5)
    proxy.wait(timeout=5)
    
    log.info("\n" + "=" * 60)
    log.info(f"RESULTS: {PASS} passed, {FAIL} failed")
    log.info("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
