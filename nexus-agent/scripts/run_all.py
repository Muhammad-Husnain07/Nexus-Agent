"""Start infrastructure, register tools, and run comprehensive tests."""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
import uuid

import httpx

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

BASE = "http://localhost:8000/api/v1"
PROXY_BASE = "http://localhost:8081"


# ─── Tool Definitions ───────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web for information on any topic. Returns title, URL, and snippet for each result.",
        "purpose": "Use when the user asks to search, look up, find, or research something online.",
        "endpoint_url": f"{PROXY_BASE}/search",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (1-20)", "default": 5},
            },
            "required": ["q"],
        },
        "tags": ["search", "web", "read"],
        "category": "search",
        "risk_level": "low",
        "requires_approval": False,
    },
    {
        "name": "create_bookmark",
        "description": "Save a web bookmark with URL, title, and optional tags.",
        "purpose": "Use when the user asks to save, bookmark, or store a web link.",
        "endpoint_url": f"{PROXY_BASE}/bookmarks",
        "http_method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Bookmark URL"},
                "title": {"type": "string", "description": "Bookmark title"},
            },
            "required": ["url", "title"],
        },
        "tags": ["bookmarks", "write", "create"],
        "category": "bookmarks",
        "risk_level": "low",
        "requires_approval": False,
    },
    {
        "name": "update_bookmark",
        "description": "Replace ALL fields of an existing bookmark.",
        "purpose": "Use when the user wants to completely overwrite a bookmark's data.",
        "endpoint_url": f"{PROXY_BASE}/bookmarks/{{bookmark_id}}",
        "http_method": "PUT",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "url": {"type": "string", "description": "New URL"},
                "title": {"type": "string", "description": "New title"},
            },
            "required": ["bookmark_id", "url", "title"],
        },
        "tags": ["bookmarks", "write", "update"],
        "category": "bookmarks",
        "risk_level": "low",
        "requires_approval": False,
    },
    {
        "name": "patch_bookmark",
        "description": "Partially update a bookmark — only send the fields that changed.",
        "purpose": "Use for partial updates to bookmark fields.",
        "endpoint_url": f"{PROXY_BASE}/bookmarks/{{bookmark_id}}",
        "http_method": "PATCH",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to update"},
                "title": {"type": "string", "description": "New title (optional)"},
            },
            "required": ["bookmark_id"],
        },
        "tags": ["bookmarks", "write", "patch"],
        "category": "bookmarks",
        "risk_level": "low",
        "requires_approval": False,
    },
    {
        "name": "delete_bookmark",
        "description": "Permanently delete a bookmark. CANNOT be undone.",
        "purpose": "Use ONLY when the user explicitly asks to delete a bookmark.",
        "endpoint_url": f"{PROXY_BASE}/bookmarks/{{bookmark_id}}",
        "http_method": "DELETE",
        "input_schema": {
            "type": "object",
            "properties": {
                "bookmark_id": {"type": "string", "description": "ID of the bookmark to delete"},
            },
            "required": ["bookmark_id"],
        },
        "tags": ["bookmarks", "admin", "delete"],
        "category": "bookmarks",
        "risk_level": "high",
        "requires_approval": True,
    },
]


# ─── Tests ──────────────────────────────────────────────────────────────────

async def test_health(client: httpx.AsyncClient):
    r = await client.get("http://localhost:8000/healthz")
    assert r.status_code == 200, f"healthz: {r.status_code}"
    log.info("✅  Health check passed")


async def test_tool_registration(client: httpx.AsyncClient):
    registered = 0
    for t in TOOLS:
        r = await client.post(f"{BASE}/tools", json=t)
        if r.status_code == 201:
            registered += 1
            log.info(f"  ✅  {t['name']:<25} registered")
        elif r.status_code == 409:
            log.info(f"  ⚠️   {t['name']:<25} already exists")
        else:
            log.error(f"  ❌  {t['name']:<25} {r.status_code}: {r.text[:80]}")
    log.info(f"✅  Tools registered: {registered}/{len(TOOLS)}")


async def test_tool_listing(client: httpx.AsyncClient):
    r = await client.get(f"{BASE}/tools")
    assert r.status_code == 200
    items = r.json().get("items", [])
    log.info(f"✅  Tools listed: {len(items)} total")
    for t in items:
        log.info(f"    {t['name']:<25} {t.get('http_method', '?'):<6} "
                 f"risk={t.get('risk_level', '?'):<7} "
                 f"approval={t.get('requires_approval', False)}")


async def test_semantic_search(client: httpx.AsyncClient):
    r = await client.get(f"{BASE}/tools/search?q=search+the+web&k=5")
    assert r.status_code == 200
    results = r.json()
    log.info(f"✅  Semantic search returned {len(results)} results")
    for r2 in results:
        log.info(f"    {r2['tool']['name']:<25} score={r2.get('score', 0):.4f}")
    assert len(results) > 0, "Semantic search should find web_search"
    assert results[0]["tool"]["name"] == "web_search", "web_search should be top result"


async def test_create_session(client: httpx.AsyncClient):
    r = await client.post(f"{BASE}/sessions", json={"title": "Comprehensive Test"})
    assert r.status_code == 200
    data = r.json()
    sid = data["id"]
    log.info(f"✅  Session created: {sid}")
    return sid


async def test_chat_stream(client: httpx.AsyncClient, session_id: str):
    """Send a message and verify the SSE event stream."""
    log.info(f"\n🔍 Testing chat SSE stream (session: {session_id[:8]}...)")
    
    async with client.stream(
        "POST", f"{BASE}/sessions/{session_id}/chat",
        json={"message": "Search the web for the latest AI developments", "stream": True},
        timeout=120,
    ) as resp:
        assert resp.status_code == 200, f"Chat: {resp.status_code}"
        log.info(f"    SSE connected (status={resp.status_code})")
        
        events = []
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
        
        log.info(f"    Events received: {len(events)}")
        for e in events:
            log.info(f"      - {e}")
        
        assert "plan_created" in events, "Missing plan_created event"
        assert "final_response" in events, "Missing final_response event"
        assert "done" in events, "Missing done event"
        log.info("✅  Chat SSE streaming verified")


async def test_multi_turn(client: httpx.AsyncClient, session_id: str):
    """Test multi-turn conversation within the same session."""
    log.info(f"\n🔍 Testing multi-turn conversation")
    
    # Turn 1: Search
    r = await client.post(
        f"{BASE}/sessions/{session_id}/chat",
        json={"message": "My name is Alice and I love AI technology", "stream": False},
        timeout=120,
    )
    assert r.status_code == 200
    turn1 = r.json()
    log.info(f"    Turn 1 complete: final_response={'Yes' if turn1.get('final_response') else 'No'}")
    
    # Turn 2: Follow-up (should have context from turn 1)
    r = await client.post(
        f"{BASE}/sessions/{session_id}/chat",
        json={"message": "What is my name and what do I love?", "stream": False},
        timeout=120,
    )
    assert r.status_code == 200
    turn2 = r.json()
    resp_text = str(turn2.get("final_response", ""))
    log.info(f"    Turn 2 response: {resp_text[:100]}...")
    assert "Alice" in resp_text or "alice" in resp_text.lower(), \
        f"Agent should remember name from turn 1. Response: {resp_text[:200]}"
    log.info("✅  Multi-turn conversation verified")


async def test_memory_query(client: httpx.AsyncClient, session_id: str):
    """Test memory query - agent should recall past conversation."""
    log.info(f"\n🔍 Testing memory query")
    
    r = await client.post(
        f"{BASE}/sessions/{session_id}/chat",
        json={"message": "What did we talk about so far?", "stream": False},
        timeout=120,
    )
    assert r.status_code == 200
    resp_text = str(r.json().get("final_response", ""))
    log.info(f"    Memory response: {resp_text[:150]}...")
    
    if "Alice" in resp_text or "alice" in resp_text.lower():
        log.info("✅  Memory query: agent recalled Alice")
    else:
        log.warning("⚠️   Memory query: agent may not have recalled details")
        log.info(f"    Full response: {resp_text[:300]}")


async def test_session_messages(client: httpx.AsyncClient, session_id: str):
    """Test retrieving messages for a session."""
    r = await client.get(f"{BASE}/sessions/{session_id}/messages")
    assert r.status_code == 200
    msgs = r.json().get("items", [])
    log.info(f"✅  Session messages: {len(msgs)} messages")
    for m in msgs:
        log.info(f"    {m['role']:10s}: {str(m.get('content', {}))[:60]}...")


async def test_session_list(client: httpx.AsyncClient):
    """Test session listing."""
    r = await client.get(f"{BASE}/sessions")
    assert r.status_code == 200
    sessions = r.json().get("items", [])
    log.info(f"✅  Sessions listed: {len(sessions)} total")


async def test_greeting(client: httpx.AsyncClient):
    """Test greeting routing."""
    sid = str(uuid.uuid4())
    r = await client.post(
        f"{BASE}/sessions/{sid}/chat",
        json={"message": "Hello! How are you today?", "stream": False},
        timeout=60,
    )
    assert r.status_code == 200
    log.info("✅  Greeting handled")


async def test_meta_question(client: httpx.AsyncClient):
    """Test meta question (what can you do?)."""
    sid = str(uuid.uuid4())
    r = await client.post(
        f"{BASE}/sessions/{sid}/chat",
        json={"message": "What tools do you have available?", "stream": False},
        timeout=60,
    )
    assert r.status_code == 200
    resp_text = str(r.json().get("final_response", ""))
    log.info(f"✅  Meta question answered ({len(resp_text)} chars)")


# ─── Main ───────────────────────────────────────────────────────────────────

async def main():
    log.info("=" * 60)
    log.info("NEXUS AGENT — COMPREHENSIVE TEST SUITE")
    log.info("=" * 60)
    
    async with httpx.AsyncClient(timeout=30) as client:
        # Phase 1: Health
        await test_health(client)
        
        # Phase 2: Tool Registration
        await test_tool_registration(client)
        await test_tool_listing(client)
        await test_semantic_search(client)
        
        # Phase 3: Sessions & Chat
        session_id = await test_create_session(client)
        await test_session_list(client)
        await test_greeting(client)
        await test_meta_question(client)
        
        # Phase 4: Multi-turn conversation
        await test_chat_stream(client, session_id)
        await test_multi_turn(client, session_id)
        await test_memory_query(client, session_id)
        await test_session_messages(client, session_id)
    
    log.info("\n" + "=" * 60)
    log.info("ALL TESTS COMPLETED")
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
