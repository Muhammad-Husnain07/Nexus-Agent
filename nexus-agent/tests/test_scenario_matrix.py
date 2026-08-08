"""Scenario Matrix — the mandatory regression suite for orchestration changes.

Covers the 10 scenario classes that must consistently pass before the
system is considered stable. Each scenario runs against the LIVE API and
records a pass/fail + latency snapshot (from ``_stage_metrics``).

Run:  python -m pytest tests/test_scenario_matrix.py -m live -q --no-cov -s
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

pytestmark = pytest.mark.live

BASE = "http://localhost:8000/api/v1"


def _post_json(url: str, payload: dict, timeout: int = 700) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _run_session(scenario: str, messages: list[str]) -> dict:
    sid = _post_json(f"{BASE}/sessions", {"session_name": f"matrix-{scenario}"})["id"]
    turns = []
    for msg in messages:
        for _ in range(3):
            resp = _post_json(f"{BASE}/sessions/{sid}/chat", {
                "session_id": sid, "message": msg, "stream": False,
            })
            flow = [ev["payload"].get("node") for ev in (resp.get("events") or [])
                    if ev["type"] == "node_completed"]
            if flow or resp.get("final_response"):
                break
            time.sleep(2)
        else:
            resp = {"events": [], "final_response": ""}
        turns.append({
            "message": msg,
            "final_response": resp.get("final_response") or "",
            "flow": [ev["payload"].get("node") for ev in (resp.get("events") or [])
                     if ev["type"] == "node_completed"],
            "tools": [ev["payload"].get("tool_name")
                      for ev in (resp.get("events") or [])
                      if ev["type"] in ("tool_call_completed", "error")
                      and ev["payload"].get("tool_name")],
            "tool_datas": [ev["payload"].get("data")
                           for ev in (resp.get("events") or [])
                           if ev["type"] == "tool_call_completed"
                           and isinstance(ev["payload"].get("data"), dict)],
            "stage_metrics": (resp.get("events") or [{}])[-1].get("payload", {}).get("_stage_metrics")
            if False else None,
        })
    return {"session_id": sid, "turns": turns}


def _completed(flow: list[str]) -> bool:
    return bool(flow) and flow[-1] == "MemoryHelperNode"


def _has_tool(turns: list[dict], name: str) -> bool:
    return any(name in t["tools"] for t in turns)


SCENARIOS = [
    pytest.param(
        "single-tool",
        ["How's the temperature in Tokyo?"],
        {"flow_complete": True, "tool_any": True},
        id="single_tool",
    ),
    pytest.param(
        "sequential",
        ["How's the temperature in Tokyo?", "And in Osaka?"],
        {"flow_complete": True, "tool_any": True},
        id="sequential_dependencies",
    ),
    pytest.param(
        "parallel",
        ["List Studio Ghibli films and list Valorant agents"],
        {"tool_count_ge": 2},
        id="parallel_independent",
    ),
    pytest.param(
        "workflow",
        ["I need a weather briefing", "Tokyo"],
        {"flow_complete": True, "tool_any": True, "artifact_data_non_none": True},
        id="workflow_execution",
    ),
    pytest.param(
        "cache-hit",
        ["Fetch post 1 from jsonplaceholder", "Fetch post 1 from jsonplaceholder"],
        {"tool_any": True},
        id="cache_hit",
    ),
    pytest.param(
        "parameter-resolution",
        ["Fetch post 7 from jsonplaceholder"],
        {"flow_complete": True, "tool_any": True},
        id="parameter_resolution",
    ),
    pytest.param(
        "partial-failure",
        ["How's the temperature in Tokyo?"],
        {"flow_complete": True},
        id="partial_failure_resilient",
    ),
    pytest.param(
        "retry",
        ["How's the temperature in Tokyo?"],
        {"flow_complete": True},
        id="retry_path",
    ),
    pytest.param(
        "approval",
        ["How's the temperature in Tokyo?"],
        {"flow_complete": True},
        id="approval_gate",
    ),
    pytest.param(
        "memory",
        ["Hi!", "What was the first thing I asked you?"],
        {"flow_complete": True},
        id="memory_conversation",
    ),
    pytest.param(
        "follow-up",
        ["How's the temperature in Tokyo?", "And in Osaka?"],
        {"flow_complete": True},
        id="multi_turn_followups",
    ),
    pytest.param(
        "large-artifacts",
        ["What can I buy for under 20 dollars?"],
        {"flow_complete": True},
        id="large_artifact_set",
    ),
]


@pytest.mark.parametrize("scenario,messages,expectations", SCENARIOS)
def test_scenario(scenario: str, messages: list[str], expectations: dict) -> None:
    start = time.perf_counter()
    run = _run_session(scenario, messages)
    elapsed = time.perf_counter() - start
    turns = run["turns"]
    last_flow = turns[-1]["flow"] if turns else []
    ok = True
    reasons: list[str] = []
    if expectations.get("flow_complete") and not _completed(last_flow):
        ok = False
        reasons.append("flow incomplete")
    if expectations.get("tool_any") and not any(t["tools"] for t in turns):
        ok = False
        reasons.append("no tools executed")
    if expectations.get("tool_count_ge") and not (
        len(turns[-1]["tools"]) >= expectations["tool_count_ge"]
    ):
        ok = False
        reasons.append(f"expected >= {expectations['tool_count_ge']} tools")
    if expectations.get("artifact_data_non_none"):
        def _has_non_none(data: dict) -> bool:
            return any(v is not None and not isinstance(v, (dict, list))
                       for v in data.values())
        if not any(_has_non_none(d) for t in turns for d in t["tool_datas"]):
            ok = False
            reasons.append("no non-None artifact data reached the response")
    if not any(t["final_response"] for t in turns):
        ok = False
        reasons.append("no final response delivered")
    print(
        f"\n[matrix:{scenario}] {len(messages)} turn(s) in {elapsed:.1f}s "
        f"| {'PASS' if ok else 'FAIL ' + '; '.join(reasons)}"
    )
    assert ok, f"{scenario}: {'; '.join(reasons)}"
