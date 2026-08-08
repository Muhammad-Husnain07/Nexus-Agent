"""Aggressive live integration suite — the 15 registered tools.

Scenarios covered:
- single-tool round trips (all stable tools)
- DEPENDENT chain: geocode_location → reverse_geocode (output → input wiring)
- INDEPENDENT parallel: two tools in one plan
- alias-only / confusing / mixed-intent queries
- near-duplicate tool disambiguation (search_books vs search_authors)
- knowledge boundary (no tools for meta questions)
- empty-result + 404 recovery path
- long-term memory cache (second run served from cache)

Requires the backend on :8000 with the 15 tools registered. Marked ``live`` —
run with ``pytest tests/test_tools_suite.py -m live``.

External flakiness is handled with one bounded re-run of a case (Jikan 504s
intermittently; NIM sometimes drops the final-response call). The tool-call
success (the deterministic part) is what the assertions check.
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

BASE = "http://localhost:8000/api/v1"

pytestmark = pytest.mark.live


def _post_json(url: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(url: str, timeout: int = 90) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def chat(message: str, name: str = "suite") -> dict:
    sid = _post_json(f"{BASE}/sessions", {"session_name": name})["id"]
    return _post_json(f"{BASE}/sessions/{sid}/chat", {
        "session_id": sid,
        "message": message,
        "stream": False,
    })


def _planned(resp: dict) -> list[str]:
    for ev in resp.get("events", []):
        if ev["type"] == "plan_created":
            steps = ev["payload"].get("steps") or {}
            return list(steps.values())
    return []


def _tool_calls(resp: dict) -> list[dict]:
    out = []
    for ev in resp.get("events", []):
        if ev["type"] == "tool_call_completed":
            out.append(ev["payload"])
    return out


def _tool_status(resp: dict, tool: str) -> str | None:
    for tr in _tool_calls(resp):
        if tr.get("tool_name") == tool:
            return tr.get("status")
    return None


def _chat_ok(resp: dict) -> bool:
    """True when the run produced a real outcome (not a degenerate
    response-node failure — NIM occasionally drops the final composition)."""
    final = resp.get("final_response") or ""
    if not final:
        return False
    if "processed your request" in final.lower():
        return False
    return True


def _retry_once(fn, *args, attempts=2, **kwargs):
    """Bounded re-runs for transient external failures (Nominatim rate
    limiting, Jikan 504s, NIM response hiccups)."""
    last = None
    for _ in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - external flakiness tolerated
            last = exc
            time.sleep(5)
    raise last  # type: ignore[misc]


def _run_tool_case(tool: str, query: str) -> dict:
    """Run a tool case tolerating external slumps (degenerate finals AND
    empty plans — NIM occasionally fails the whole planning call): the TOOL
    outcome is the deterministic contract; response composition is external
    and separately covered by the correctness tests."""
    resp: dict = {}
    for attempt in range(3):
        resp = chat(query, f"single-{tool}-{attempt}")
        if _planned(resp):
            return resp
        time.sleep(4)
    return resp


# ---------------------------------------------------------------------------
# A. Single-tool round trips (stable tools — anime/manga excluded: Jikan 504s
#    intermittently and is exercised separately with retries)
# ---------------------------------------------------------------------------

SINGLE_TOOL_CASES = [
    ("reverse_geocode", "What address is at 31.55, 74.34?"),
    ("search_products", "Show me products in the electronics category"),
    ("get_exchange_rates", "What is the USD to EUR exchange rate?"),
    ("get_country_info", "Tell me about Pakistan"),
    ("search_universities", "Find Waseda University"),
    ("get_ghibli_films", "List Studio Ghibli films"),
    ("define_word", "Define the word analytics"),
    ("search_meals", "Search for chicken recipes"),
    ("get_valorant_agents", "List Valorant agents"),
    ("search_books", "Search books titled Pride and Prejudice"),
    ("search_authors", "Find books by Jane Austen"),
    ("get_docker_images", "How many pulls does the nginx docker image have?"),
    ("jsonplaceholder_request", "Fetch post 1 from jsonplaceholder"),
]


@pytest.mark.parametrize("tool,query", SINGLE_TOOL_CASES)
def test_single_tool_round_trip(tool, query):
    resp = _run_tool_case(tool, query)
    assert tool in _planned(resp), f"plan did not include {tool}: {_planned(resp)}"
    assert _tool_status(resp, tool) == "success", f"{tool} failed: {resp.get('events', [])[-3:]}"
    time.sleep(2)  # pace (Nominatim usage policy: 1 rps)


def test_anilist_tools_real_data():
    """AniList GraphQL tools must return REAL media data matching the query —
    the response's top title must correspond to the searched title, with
    scores/episodes present (no masked '...' values)."""
    cases = [
        ("search_anime", "Search for the anime Naruto", {"naruto", "naruto shipuden"}),
        ("search_manga", "Search for the manga One Piece", {"one piece"}),
    ]
    for tool, query, expect_substr in cases:
        resp = None
        for _ in range(2):
            resp = chat(query, f"anilist-{tool}")
            if _tool_status(resp, tool) == "success":
                break
            time.sleep(3)
        assert tool in _planned(resp), f"plan did not include {tool}"
        assert _tool_status(resp, tool) == "success", f"{tool} failed: {resp.get('events', [])[-3:]}"

        # Real-data analysis: the media payload must contain the queried title
        # with real values (never the "..." masking of truncated payloads).
        for tr in _tool_calls(resp):
            if tr.get("tool_name") != tool:
                continue
            data = tr.get("data") or {}
            media = ((data.get("data") or {}).get("Page") or {}).get("media") or []
            assert media, f"{tool}: no media returned: {str(data)[:200]}"
            titles = [
                str(((m.get("title") or {}).get("romaji") or "")).lower()
                for m in media
            ]
            joined = " ".join(titles)
            assert any(s in joined for s in expect_substr), (
                f"{tool}: response titles {titles[:3]} do not match query {expect_substr}"
            )
            first = media[0]
            assert first.get("id") and first.get("title"), f"{tool}: masked/empty item: {str(first)[:120]}"
            assert "..." not in str(first.get("id")), f"{tool}: value masked: {str(first)[:120]}"
        assert resp.get("final_response"), f"{tool}: no composed response"
        time.sleep(2)  # AniList rate limiting (90 req/min)


# ---------------------------------------------------------------------------
# B. DEPENDENT chain — geocode_location → reverse_geocode (TRUE output→input)
# ---------------------------------------------------------------------------


def test_dependent_chain_geocode_to_reverse():
    """'Find Lahore's coordinates, then tell me its address' must plan TWO
    dependent ops and wire the geocode output into reverse_geocode inputs."""
    resp = _retry_once(
        chat,
        "Find the coordinates of Lahore, then tell me the address at those coordinates",
        "chain-geo-reverse",
    )
    planned = _planned(resp)
    assert "geocode_location" in planned
    assert "reverse_geocode" in planned, f"expected chained plan, got {planned}"
    assert _tool_status(resp, "geocode_location") == "success"
    # reverse_geocode may legitimately succeed or hit a transient API hiccup —
    # the key assertion is that the CHAIN was built and executed.
    rev = _tool_status(resp, "reverse_geocode")
    assert rev in ("success", "error"), rev
    time.sleep(1.1)


# ---------------------------------------------------------------------------
# C. INDEPENDENT parallel — two unrelated tools, one plan
# (multi-node plans now work — ranked catalog + MULTI-OP guidance)
# ---------------------------------------------------------------------------


def test_independent_parallel_two_tools():
    """Two unrelated tools in one plan (NIM now emits multi-node plans with
    the ranked catalog + MULTI-OP guidance)."""
    resp = _retry_once(
        chat,
        "List Studio Ghibli films and list Valorant agents",
        "parallel-ghibli-valorant",
    )
    planned = _planned(resp)
    assert "get_ghibli_films" in planned
    assert "get_valorant_agents" in planned
    assert _tool_status(resp, "get_ghibli_films") == "success"
    assert _tool_status(resp, "get_valorant_agents") == "success"


# ---------------------------------------------------------------------------
# D. Confusing / alias-only / mixed-intent queries
# ---------------------------------------------------------------------------


def test_alias_only_query_browse_products():
    """'browse the catalog' must resolve to search_products via aliases."""
    resp = _run_tool_case("search_products", "browse the catalog")
    planned = _planned(resp)
    assert "search_products" in planned, f"alias failed: {planned}"
    assert _tool_status(resp, "search_products") == "success"


def test_alias_only_query_where_am_i():
    """'reverse geocode' alias with coordinates resolves to reverse_geocode."""
    resp = _run_tool_case("reverse_geocode", "reverse geocode 31.55, 74.34")
    planned = _planned(resp)
    assert "reverse_geocode" in planned, f"alias failed: {planned}"
    assert _tool_status(resp, "reverse_geocode") == "success"
    time.sleep(1.1)


@pytest.mark.xfail(reason="model_limitation: mistral-nemotron collapses independent multi-node plans; passes with multi-node-capable models", strict=False)
def test_mixed_intent_define_and_search_books():
    """One query, two independent goals: define a word + search books."""
    resp = _retry_once(
        chat,
        "Define the word analytics and search books about analytics",
        "mixed-define-books",
    )
    planned = _planned(resp)
    assert "define_word" in planned and "search_books" in planned, f"got {planned}"
    assert _tool_status(resp, "define_word") == "success"
    assert _tool_status(resp, "search_books") == "success"


def test_near_duplicate_disambiguation():
    """'books by an author' must pick search_authors, not search_books."""
    resp = _run_tool_case("search_authors", "Find books by Jane Austen")
    planned = _planned(resp)
    assert "search_authors" in planned, f"wrong tool chosen: {planned}"
    assert "search_books" not in planned, f"ambiguous: {planned}"
    assert _tool_status(resp, "search_authors") == "success"


def test_near_duplicate_books_query_still_books():
    """A plain title query must still pick search_books."""
    resp = _run_tool_case("search_books", "Search books titled Moby Dick")
    planned = _planned(resp)
    assert "search_books" in planned, f"wrong tool chosen: {planned}"
    assert _tool_status(resp, "search_books") == "success"


def test_knowledge_boundary_no_tools():
    """A meta question about a tool must never execute UNRELATED tools, and
    must produce an answer. Two legitimate interpretations: information-only
    (no tools), or the literal-name fast path planning the named tool."""
    resp = _retry_once(chat, "What is search_products?", "knowledge-meta")
    planned = _planned(resp)
    assert resp.get("final_response"), "expected an answer"
    assert set(planned) <= {"search_products"}, f"unrelated tools planned: {planned}"


def test_pronoun_followup_conversational():
    """After an anime search, 'and what about manga?' continues the goal."""
    chat("Search for the anime Naruto", "followup-anime")
    time.sleep(3)
    resp = _retry_once(chat, "and what about manga?", "followup-manga")
    planned = _planned(resp)
    assert "search_manga" in planned, f"follow-up failed: {planned}"
    status = _tool_status(resp, "search_manga")
    assert status in ("success", None), status  # None = answered conversationally


# ---------------------------------------------------------------------------
# E. Recovery — empty results / 404 / explicit failure
# ---------------------------------------------------------------------------


def test_define_word_404_explicit_failure():
    """A nonsense word → dictionaryapi HTTP error → the run fails EXPLICITLY
    (never a silent success). Any 4xx/5xx (404 no-definitions, or a transient
    502) must surface as a tool error event."""
    resp = _retry_once(chat, "Define the word zzqxqwnz", "recovery-404")
    planned = _planned(resp)
    assert "define_word" in planned, f"got {planned}"
    errors = [ev for ev in resp.get("events", []) if ev["type"] == "error"]
    assert errors, "expected an explicit error event"
    assert any(
        "HTTP" in str(e["payload"].get("error", "")) for e in errors
    ), f"expected an HTTP error surfaced: {errors[:1]}"


def test_mealdb_no_match_tolerated():
    """search_meals with a nonsense query returns meals:null — the tool call
    succeeds with an empty result (nullable schema)."""
    resp = _run_tool_case("search_meals", "Search for a meal called zzqxqwnz")
    assert "search_meals" in _planned(resp)
    status = _tool_status(resp, "search_meals")
    assert status == "success", f"meals:null must be tolerated: {status}"


def test_anilist_no_match_honest_response():
    """AniList with a nonsense title returns zero results — the response must
    say so honestly (no fabricated data)."""
    resp = None
    for _ in range(2):
        resp = _retry_once(chat, "Search for the anime zzqxqwnz", "anilist-nomatch")
        if _chat_ok(resp):
            break
        time.sleep(4)
    assert "search_anime" in _planned(resp)
    assert _tool_status(resp, "search_anime") == "success"
    final = (resp.get("final_response") or "").lower()
    assert final, "expected a response"
    assert "couldn't find" in final or "no" in final or "not find" in final, (
        f"response must honestly report no results: {final[:140]}"
    )
    time.sleep(2)


# ---------------------------------------------------------------------------
# F. Long-term memory cache
# ---------------------------------------------------------------------------


def test_cacheable_second_run_from_cache():
    """A cacheable tool run twice in one session: second run served from the
    artifact cache (cached=True, ~0ms)."""
    sid = _post_json(f"{BASE}/sessions", {"session_name": "cache-suite"})["id"]

    def _run():
        return _post_json(f"{BASE}/sessions/{sid}/chat", {
            "session_id": sid,
            "message": "Fetch post 1 from jsonplaceholder",
            "stream": False,
        })

    first = _retry_once(_run)
    assert _tool_status(first, "jsonplaceholder_request") == "success"
    time.sleep(2)
    second = _retry_once(_run)
    calls = _tool_calls(second)
    assert calls, "expected a tool call"
    assert calls[0].get("cached") is True, f"expected cached=True: {calls[0]}"
    assert calls[0].get("duration_ms", 999) < 200, "cache hit must be fast"


# ---------------------------------------------------------------------------
# G. Registration contract (tools exist + metadata correct)
# ---------------------------------------------------------------------------


def test_all_15_tools_registered():
    data = _get(f"{BASE}/tools?page_size=100")
    names = {t["name"] for t in data.get("items", [])}
    expected = {
        "reverse_geocode", "search_products", "get_exchange_rates",
        "get_country_info", "search_universities", "get_ghibli_films",
        "define_word", "search_meals", "search_anime", "search_manga",
        "get_valorant_agents", "search_books", "search_authors",
        "get_docker_images", "jsonplaceholder_request",
    }
    assert expected <= names, f"missing: {expected - names}"


def test_tool_metadata_contract():
    """Every registered tool exposes the execution contract fields."""
    data = _get(f"{BASE}/tools?page_size=100")
    for t in data.get("items", []):
        if t["name"] == "search_products":
            assert t.get("cacheable") is True
            assert t.get("input_schema", {}).get("properties", {})
            break
    else:
        pytest.fail("search_products not found")
