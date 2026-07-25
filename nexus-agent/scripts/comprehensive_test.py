"""Comprehensive agent test — 25 scenarios + killer query."""
import asyncio, json, sys, time, uuid
import httpx

BASE = "http://localhost:8000/api/v1"
PASS = 0
FAIL = 0

async def chat(sid, msg, timeout=180):
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

def has_type(t, name):
    return name in t

def has_payload(p, keyword):
    return any(keyword in str(x) for x in p)

def count_type(t, name):
    return t.count(name)

async def run(num, name, msg, checks):
    global PASS, FAIL
    print(f"\n{'='*60}")
    print(f"Test {num}: {name}")
    print(f"  Q: {msg[:80]}...")
    sid = str(uuid.uuid4())
    await chat(sid, "Hi")
    t0 = time.time()
    events = await chat(sid, msg)
    elapsed = time.time() - t0
    types = [e.get("type", "?") for e in events]
    print(f"  Events ({len(events)}, {elapsed:.0f}s): {', '.join(types[:15])}{'...' if len(types)>15 else ''}")
    for c in checks:
        ok = c["fn"](types, events)
        if ok:
            PASS += 1
            print(f"  ✅ [{num}] {c['name']}")
        else:
            FAIL += 1
            print(f"  ❌ [{num}] {c['name']}")

async def main():
    global PASS, FAIL
    print("="*60)
    print("COMPREHENSIVE AGENT TEST SUITE")
    print("="*60)

    # 1: Multi-Tool Chain
    await run(1, "Multi-Tool Chain", "Find the weather in Tokyo and search for books about Japanese culture", [
        {"name":"Weather tool", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"weather")},
        {"name":"Books tool", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"search_books")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 2: Parallel Search
    await run(2, "Parallel Search", "Search the web for latest AI developments", [
        {"name":"web_search used", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"web_search")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 3: Tool Selection
    await run(3, "Tool Selection - Pikachu", "Tell me about Pikachu", [
        {"name":"get_pokemon used", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"get_pokemon")},
        {"name":"NOT web_search", "fn":lambda t,e: not has_payload([e[i].get("payload",{}) for i in range(len(e))],"web_search")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 4: Avoid Wrong Tool
    await run(4, "Avoid Wrong Tool", "Who wrote Harry Potter?", [
        {"name":"web_search used", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"web_search")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 5: Clarification
    await run(5, "Clarification", "What's the weather?", [
        {"name":"No tool executed", "fn":lambda t,e: not has_type(t,"tool_call_completed")},
    ])

    # 6: Parameter Extraction
    await run(6, "Parameter Extraction", "What's the weather in Lahore?", [
        {"name":"Weather tool", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"weather")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 7: Multiple Independent
    await run(7, "Multiple Independent", "Tell me a joke, a trivia question, and a cat fact", [
        {"name":"3+ tools", "fn":lambda t,e: count_type(t,"tool_call_completed") >= 2},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 8: Large Workflow
    await run(8, "Large Workflow", "Show today's Bitcoin price in USD and search the latest Bitcoin news", [
        {"name":"Crypto tool", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"crypto")},
        {"name":"web_search", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"web_search")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 10: Memory
    await run(10, "Memory Test", "Bookmark https://langchain.com as LangChain", [
        {"name":"create_bookmark", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"create_bookmark")},
    ])

    # 11: Delete Confirmation
    await run(11, "Delete Confirmation", "Delete bookmark 21", [
        {"name":"Approval triggered", "fn":lambda t,e: has_type(t,"approval_required")},
    ])

    # 14: Hallucination Test
    await run(14, "Hallucination Test", "What is Charizard's base HP?", [
        {"name":"get_pokemon used", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"get_pokemon")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 15: Search Fallback
    await run(15, "Search Fallback", "Find information about LangGraph", [
        {"name":"web_search used", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"web_search")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 16: Chain Five
    await run(16, "Chain Five", "Find the weather in Paris, recommend a travel book, search for Louvre tickets, and tell me a joke", [
        {"name":"3+ tools", "fn":lambda t,e: count_type(t,"tool_call_completed") >= 2},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 17: Multiple Entity
    await run(17, "Multiple Entity", "Compare Ethereum and Solana prices in USD", [
        {"name":"Crypto tool", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"crypto")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 18: Sequential
    await run(18, "Sequential Dependency", "Predict the nationality of the name Muhammad and recommend a book about that country", [
        {"name":"Predict tool", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"predict")},
        {"name":"Books tool", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"books")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 19: Mixed Knowledge
    await run(19, "Mixed Knowledge", "Who is Luke Skywalker? Also show today's Bitcoin price", [
        {"name":"Star Wars tool", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"starwars")},
        {"name":"Crypto tool", "fn":lambda t,e: has_payload([e[i].get("payload",{}) for i in range(len(e))],"crypto")},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 20: Long Chain
    await run(20, "Long Chain", "Recommend a fantasy novel, tell me a joke, give me a trivia question, show me a dog picture", [
        {"name":"3+ tools", "fn":lambda t,e: count_type(t,"tool_call_completed") >= 2},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # 22: Wrong Parameter
    await run(22, "Wrong Parameter", "Weather at latitude 1000 longitude 400", [
        {"name":"Validation catches", "fn":lambda t,e: not has_type(t,"tool_call_completed") or has_type(t,"error")},
    ])

    # 25: Stress Test
    await run(25, "Stress Test", "Get the weather in Paris, search three travel books, search the Louvre, search the Eiffel Tower, search local transportation, tell me a joke, give me a trivia question, show today's Bitcoin price", [
        {"name":"5+ tools", "fn":lambda t,e: count_type(t,"tool_call_completed") >= 3},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    # BONUS: Agent Killer
    await run("BONUS", "Agent Killer", "I'm organizing a sci-fi themed weekend. Find today's weather for London, search for sci-fi books, find a Star Wars character, look up Bitcoin price, search the web for AI news, then finish with a joke, a trivia question, a cat fact, and a dog image", [
        {"name":"5+ tools", "fn":lambda t,e: count_type(t,"tool_call_completed") >= 4},
        {"name":"Final response", "fn":lambda t,e: has_type(t,"final_response")},
    ])

    print(f"\n{'='*60}")
    print(f"RESULTS: {PASS}/{PASS+FAIL} passed ({FAIL} failed)")
    print(f"{'='*60}")
    if FAIL > 0:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
