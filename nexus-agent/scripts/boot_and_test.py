"""Boot both servers and run tests in-process."""

import asyncio
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Disable emoji/unicode logging errors
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger(__name__)

# Import apps
import uvicorn
from scripts.web_search_server import app as proxy_app


def run_proxy():
    """Run proxy server in a separate thread."""
    uvicorn.run(proxy_app, host="0.0.0.0", port=8081, log_level="error")


def run_nexus():
    """Run nexus server in the main thread (blocking)."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))
    from nexus.main import app as nexus_app
    uvicorn.run(nexus_app, host="0.0.0.0", port=8000, log_level="error")


async def run_tests():
    """Run tests against running servers."""
    import httpx
    import uuid
    
    async with httpx.AsyncClient(timeout=30) as c:
        # Wait for servers
        for attempt in range(30):
            try:
                r = await c.get("http://localhost:8000/healthz")
                if r.status_code == 200:
                    log.info("✅ Nexus server ready")
                    break
            except Exception:
                pass
            
            try:
                r = await c.get("http://localhost:8081/search?q=test")
                if r.status_code == 200:
                    log.info("✅ Proxy server ready")
            except Exception:
                pass
            
            await asyncio.sleep(2)
        else:
            log.error("Servers not ready after 60s")
            return
        
        # Test 1: Health
        r = await c.get("http://localhost:8000/healthz")
        log.info(f"{'✅' if r.status_code==200 else '❌'} Health check: {r.status_code}")
        
        # Test 2: Register 5 tools
        tools = [
            {"name": "web_search", "description": "Search the web", "purpose": "Search",
             "endpoint_url": "http://localhost:8081/search", "http_method": "GET",
             "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
             "tags": ["search"], "category": "search", "risk_level": "low", "requires_approval": False},
            {"name": "create_bookmark", "description": "Save a bookmark", "purpose": "Save",
             "endpoint_url": "http://localhost:8081/bookmarks", "http_method": "POST",
             "input_schema": {"type": "object", "properties": {"url": {"type": "string"}, "title": {"type": "string"}}, "required": ["url", "title"]},
             "tags": ["bookmarks"], "category": "bookmarks", "risk_level": "low", "requires_approval": False},
            {"name": "update_bookmark", "description": "Update bookmark", "purpose": "Update",
             "endpoint_url": "http://localhost:8081/bookmarks/{bookmark_id}", "http_method": "PUT",
             "input_schema": {"type": "object", "properties": {"bookmark_id": {"type": "string"}, "url": {"type": "string"}, "title": {"type": "string"}}, "required": ["bookmark_id", "url", "title"]},
             "tags": ["bookmarks"], "category": "bookmarks", "risk_level": "low", "requires_approval": False},
            {"name": "patch_bookmark", "description": "Patch bookmark", "purpose": "Patch",
             "endpoint_url": "http://localhost:8081/bookmarks/{bookmark_id}", "http_method": "PATCH",
             "input_schema": {"type": "object", "properties": {"bookmark_id": {"type": "string"}, "title": {"type": "string"}}, "required": ["bookmark_id"]},
             "tags": ["bookmarks"], "category": "bookmarks", "risk_level": "low", "requires_approval": False},
            {"name": "delete_bookmark", "description": "Delete bookmark", "purpose": "Delete",
             "endpoint_url": "http://localhost:8081/bookmarks/{bookmark_id}", "http_method": "DELETE",
             "input_schema": {"type": "object", "properties": {"bookmark_id": {"type": "string"}}, "required": ["bookmark_id"]},
             "tags": ["bookmarks"], "category": "bookmarks", "risk_level": "high", "requires_approval": True},
        ]
        
        existing = await c.get("http://localhost:8000/api/v1/tools")
        existing_names = {t["name"] for t in existing.json().get("items", [])}
        
        ok = 0
        for t in tools:
            if t["name"] in existing_names:
                log.info(f"  [SKIP] {t['name']} (already exists)")
                ok += 1
                continue
            r = await c.post("http://localhost:8000/api/v1/tools", json=t)
            if r.status_code == 201:
                ok += 1
                log.info(f"  [OK] {t['name']}")
            else:
                log.info(f"  [FAIL] {t['name']}: {r.status_code}")
        log.info(f"{'[OK]' if ok==5 else '[FAIL]'} Tool registration: {ok}/5")
        
        # Test 3: List tools
        r = await c.get("http://localhost:8000/api/v1/tools")
        if r.status_code == 200:
            items = r.json().get("items", [])
            log.info(f"✅ Tools listed: {len(items)}")
            for t in items:
                log.info(f"   {t['name']:<20} {t.get('http_method','?'):<6} risk={t.get('risk_level','?'):<6} approval={t.get('requires_approval')}")
        
        # Test 4: Semantic search
        r = await c.get("http://localhost:8000/api/v1/tools/search?q=search+web&k=5")
        if r.status_code == 200:
            log.info(f"✅ Semantic search: {len(r.json())} results")
        
        # Test 5: Session
        import uuid
        sid = str(uuid.uuid4())
        r = await c.post("http://localhost:8000/api/v1/sessions", json={"title": "Test"})
        if r.status_code == 200:
            sid = r.json()["id"]
            log.info(f"✅ Session created: {sid[:8]}...")
        
        # Test 6: Chat
        log.info("\n🔍 Chat test (this may take a minute with local LLM)...")
        r = await c.post(
            f"http://localhost:8000/api/v1/sessions/{sid}/chat",
            json={"message": "Search the web for AI news", "stream": False},
            timeout=300,
        )
        if r.status_code == 200:
            data = r.json()
            fr = data.get("final_response", "")
            events = data.get("events", [])
            log.info(f"✅ Chat complete: {len(fr)} chars, {len(events)} events")
            for e in events:
                log.info(f"   - {e.get('type','?')}")
            log.info(f"   Response: {fr[:200]}...")
        else:
            log.error(f"❌ Chat failed: {r.status_code}")
        
        # Test 7: Multi-turn
        log.info("\n🔍 Multi-turn test...")
        r2 = await c.post(
            f"http://localhost:8000/api/v1/sessions/{sid}/chat",
            json={"message": "What just happened? Summarize what we did.", "stream": False},
            timeout=300,
        )
        if r2.status_code == 200:
            fr2 = r2.json().get("final_response", "")
            log.info(f"✅ Multi-turn: {len(fr2)} chars")
        else:
            log.error(f"❌ Multi-turn failed: {r2.status_code}")
        
        # Test 8: Messages
        r = await c.get(f"http://localhost:8000/api/v1/sessions/{sid}/messages")
        if r.status_code == 200:
            msgs = r.json().get("items", [])
            log.info(f"✅ Messages: {len(msgs)} total")
            for m in msgs:
                log.info(f"   {m['role']:<10}: {str(m.get('content',''))[:60]}")
        
        # Test 9: Session list
        r = await c.get("http://localhost:8000/api/v1/sessions")
        if r.status_code == 200:
            log.info(f"✅ Sessions: {len(r.json().get('items',[]))} total")
        
        log.info("\n" + "=" * 50)
        log.info("ALL TESTS COMPLETED")
        log.info("=" * 50)


if __name__ == "__main__":
    # Start proxy in a thread
    t = threading.Thread(target=run_proxy, daemon=True)
    t.start()
    
    # Run nexus in another thread
    t2 = threading.Thread(target=run_nexus, daemon=True)
    t2.start()
    
    # Run tests
    asyncio.run(run_tests())
