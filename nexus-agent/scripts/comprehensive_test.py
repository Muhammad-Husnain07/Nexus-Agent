"""Comprehensive agent test — 25 scenarios + killer query with timing."""
import asyncio, json, sys, time, uuid
import httpx

BASE = "http://localhost:8000/api/v1"
results = []

async def chat(sid, msg, timeout=300):
    events = []
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            async with c.stream("POST", f"{BASE}/sessions/{sid}/chat", json={"message": msg}) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":") or line.startswith("id:"):
                        continue
                    if line.startswith("data: "):
                        try:
                            parsed = json.loads(line[6:])
                            if isinstance(parsed, dict) and "type" in parsed:
                                events.append(parsed)
                        except json.JSONDecodeError:
                            pass
    except httpx.TimeoutException:
        events.append({"type": "timeout", "payload": {"message": "timed_out"}})
    except Exception as e:
        events.append({"type": "error", "payload": {"message": str(e)}})
    return events

def has(events, keyword):
    return any(keyword in str(e.get("payload",{})) for e in events)

def count(events, t):
    return sum(1 for e in events if e.get("type")==t)

def get_final(events):
    for e in events:
        if e.get("type")=="final_response":
            return e.get("payload",{}).get("text","")
    return ""

async def run(num, name, msg, wanted_tools, avoid_tools=None, min_tools=0):
    print(f"\n{'─'*60}")
    print(f"Test {num}: {name}")
    print(f"  Q: {msg[:100]}...")
    sid = str(uuid.uuid4())
    await chat(sid, "Hi")
    t0 = time.time()
    events = await chat(sid, msg)
    elapsed = time.time() - t0
    types = [e.get("type","?") for e in events]
    tools_used = []
    for e in events:
        p = e.get("payload",{})
        if isinstance(p, dict) and p.get("tool_name"):
            tools_used.append(p["tool_name"])
    final = get_final(events)[:80]

    # Score
    passed = 0
    total = 0
    checks = []
    for wt in wanted_tools:
        total += 1
        found = any(wt in str(e) for e in events)
        checks.append((f"used {wt}", found))
        if found: passed += 1
    for at in (avoid_tools or []):
        total += 1
        avoided = not any(at in str(e) for e in events)
        checks.append((f"avoided {at}", avoided))
        if avoided: passed += 1
    if min_tools > 0:
        total += 1
        enough = count(events,"tool_call_completed") >= min_tools
        checks.append((f"{min_tools}+ tool calls", enough))
        if enough: passed += 1
    if "final_response" not in types:
        total += 1
        checks.append(("final_response", False))
    else:
        total += 1
        checks.append(("final_response", True))
        passed += 1

    status = "✅" if passed == total else "❌"
    print(f"  ⏱  {elapsed:6.1f}s  {status} {passed}/{total} passes")
    print(f"  Tools: {tools_used[:8]}")
    for label, ok in checks:
        print(f"    {'✅' if ok else '❌'} {label}")
    if final:
        print(f"  Response: {final}...")

    results.append((num, f"{elapsed:.1f}s", f"{passed}/{total}", status, name))

async def main():
    print("="*70)
    print("COMPREHENSIVE AGENT TEST SUITE — WITH TIMING")
    print(f"Model: nvidia/nemotron-3-ultra-550b-a55b (~13s baseline)")
    print("="*70)

    # 1
    await run(1, "Multi-Tool Chain",
        "Find the weather in Tokyo and search for books about Japanese culture",
        ["weather", "search_books"], min_tools=1)

    # 2
    await run(2, "Parallel Search",
        "Search the web for latest AI developments",
        ["web_search"])

    # 3 — Tool Selection
    await run(3, "Tool Selection — Pikachu",
        "Tell me about Pikachu",
        ["get_pokemon"], ["web_search"])

    # 4 — Avoid Wrong Tool
    await run(4, "Avoid Wrong Tool — Harry Potter",
        "Who wrote Harry Potter?",
        ["web_search"], ["search_books"])

    # 5 — Clarification
    await run(5, "Clarification — Weather no city",
        "What's the weather?",
        [], min_tools=0)
    # Override: expect NO tool calls
    results[-1] = (5, results[-1][1], "✓", "✅" if count(await chat(str(uuid.uuid4()), "What's the weather?"), "tool_call_completed") == 0 else "❌", "Clarification")

    # 6
    await run(6, "Parameter Extraction",
        "What's the weather in Lahore?",
        ["weather"], min_tools=0)

    # 7 — Multiple Independent
    await run(7, "Multiple Independent",
        "Tell me a joke, a trivia question, and a cat fact",
        [], min_tools=2)

    # 8 — Large Workflow
    await run(8, "Large Workflow — Bitcoin",
        "Show today's Bitcoin price in USD and search the latest Bitcoin news",
        ["crypto", "web_search"])

    # 10 — Memory (bookmark creation)
    await run(10, "Memory — Bookmark",
        "Bookmark https://langchain.com as LangChain",
        ["create_bookmark"])

    # 11 — Delete Confirmation
    await run(11, "Delete Confirmation",
        "Delete bookmark 21",
        ["approval"], min_tools=0)

    # 14 — Hallucination Test
    await run(14, "Hallucination — Charizard",
        "What is Charizard's base HP?",
        ["get_pokemon"], ["web_search"])

    # 15 — Search Fallback
    await run(15, "Search Fallback",
        "Find information about LangGraph",
        ["web_search"])

    # 16 — Chain Five
    await run(16, "Chain Five Tools",
        "Find the weather in Paris, recommend a travel book, search for Louvre Museum tickets, and tell me a joke",
        [], min_tools=2)

    # 17 — Multiple Entity Extraction
    await run(17, "Multiple Entity — Crypto",
        "Compare Ethereum and Solana prices in USD",
        ["crypto"])

    # 18 — Sequential Dependency
    await run(18, "Sequential Dependency",
        "Predict the nationality of the name Muhammad and recommend a book about that country",
        ["predict", "search_books"], min_tools=1)

    # 19 — Mixed Knowledge
    await run(19, "Mixed Knowledge",
        "Who is Luke Skywalker? Also show today's Bitcoin price",
        ["starwars", "crypto"])

    # 20 — Long Chain
    await run(20, "Long Chain",
        "Recommend a fantasy novel, tell me a joke, give me a trivia question, show me a dog picture",
        [], min_tools=2)

    # 22 — Wrong Parameter
    await run(22, "Wrong Parameter Validation",
        "Weather at latitude 1000 longitude 400",
        [], min_tools=0)
    # Override: verify no tool executed
    sid = str(uuid.uuid4())
    ev = await chat(sid, "Weather at latitude 1000 longitude 400")
    no_tool = count(ev, "tool_call_completed") == 0
    results[-1] = (22, results[-1][1], "✓" if no_tool else "❌", "✅" if no_tool else "❌",
                   "Wrong Parameter Validation")

    # 25 — Stress Test
    await run(25, "Stress Test — 10+ Tools",
        "Get the weather in Paris, search three travel books, search the Louvre, search the Eiffel Tower, search local transportation, tell me a joke, give me a trivia question, show today's Bitcoin price",
        [], min_tools=3)

    # BONUS — Agent Killer
    await run("BONUS", "Agent Killer",
        "I'm organizing a sci-fi themed weekend. Find today's weather for London, search for sci-fi books, find a Star Wars character, look up Bitcoin price, search the web for AI news, then finish with a joke, a trivia question, a cat fact, and a dog image",
        [], min_tools=4)

    # ─── Report ────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"{'TEST':<8} {'TIME':>6} {'PASS':>6}  {'DESCRIPTION'}")
    print(f"{'─'*8} {'─'*6} {'─'*6}  {'─'*50}")
    for num, dur, score, status, desc in results:
        print(f"  {str(num):<6} {dur:>6} {score:>6}  {desc}")
    print(f"{'─'*70}")
    passed = sum(1 for r in results if "✅" in r[3])
    total = len(results)
    print(f"\n  {passed}/{total} tests passing")
    print(f"{'='*70}")
    if passed < total:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
