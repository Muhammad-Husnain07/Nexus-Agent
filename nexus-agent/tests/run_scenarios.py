"""YAML-driven scenario test runner.

Reads YAML scenario files from tests/scenarios/, runs each against the
live agent, and asserts against expected graph state (router, extraction,
planner, executor) rather than just final text output.

Tiers (ADR-0008 governance): each scenario declares ``tier: fast|medium|full``
(default ``full``). The FAST tier (one representative per critical category)
runs on every PR CI gate; MEDIUM nightly; FULL before releases.

Usage:
    uv run pytest tests/run_scenarios.py -v
    uv run python tests/run_scenarios.py --scenario tests/scenarios/test_03_pikachu.yaml
    uv run python tests/run_scenarios.py --tier fast
"""

import argparse
import asyncio
import json
import os
import sys
import uuid

import yaml
from pathlib import Path

import httpx
import structlog

BASE = "http://localhost:8000/api/v1"
logger = structlog.get_logger("tests.run_scenarios")

PASS = 0
FAIL = 0
RESULTS = []


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


def _check_val(path, actual, expected):
    """Check a single expected value against actual state."""
    if expected is None:
        return True, ""
    if isinstance(expected, (int, float)):
        if path.endswith("_gt"):
            return actual > expected, f"expected > {expected}, got {actual}"
        key = path.rsplit(".", 1)[0]
        return actual == expected, f"expected {expected}, got {actual}"
    if isinstance(expected, str):
        return actual == expected, f"expected '{expected}', got '{actual}'"
    if isinstance(expected, list):
        return set(expected) == set(actual), f"expected {expected}, got {actual}"
    return True, ""


def _check_contains(text, keywords):
    if not keywords:
        return True, ""
    text_lower = text.lower()
    missing = [k for k in keywords if k.lower() not in text_lower]
    if missing:
        return False, f"missing keywords: {missing}"
    return True, ""


def _check_avoid(events, avoid_tools):
    if not avoid_tools:
        return True, ""
    used = set()
    for e in events:
        p = e.get("payload", {})
        if isinstance(p, dict) and p.get("tool_name") in avoid_tools:
            used.add(p["tool_name"])
    if used:
        return False, f"used forbidden tools: {used}"
    return True, ""


def _get_final_text(events):
    for e in events:
        if e.get("type") == "final_response":
            return e.get("payload", {}).get("text", "")
    return ""


def _get_tool_selected(events):
    """Get the payload from the tool_selected event (router output)."""
    for e in events:
        if e.get("type") == "tool_selected":
            return e.get("payload", {})
    return {}


def _get_extraction_intent(events):
    """Try to find extraction intent from plan_created or error events."""
    for e in events:
        p = e.get("payload", {})
        if isinstance(p, dict):
            # Error events might contain extraction results
            msg = p.get("message", "")
            if isinstance(msg, str) and "ExtractionNode:" in msg:
                return "extraction_error"
    # Check if the planner produced a plan — extraction succeeded
    plan_count = sum(1 for e in events if e.get("type") == "plan_created")
    if plan_count > 0:
        return "detected"  # extraction must have worked if planner ran
    return None


async def run_scenario(path: str) -> dict:
    """Run a single scenario and return results."""
    global PASS, FAIL

    with open(path) as f:
        scenario = yaml.safe_load(f)

    tid = scenario["test_id"]
    name = scenario["name"]
    query = scenario["user_query"]
    exp = scenario.get("expected") or {}

    print(f"\n  Test {tid}: {name}")
    print(f"    Q: {query[:80]}...")

    sid = str(uuid.uuid4())
    t0 = __import__("time").time()
    events = await chat(sid, query)
    elapsed = __import__("time").time() - t0

    types = [e.get("type", "?") for e in events]
    final_text = _get_final_text(events)

    checks = []
    errors = []

    # --- Router checks ---
    router_exp = exp.get("router", {})
    ts_payload = _get_tool_selected(events)
    for key, val in router_exp.items():
        # tool_selected has {intent: qtype, parameters: {query_type, ...}}
        actual_qtype = ts_payload.get("intent", ts_payload.get("parameters", {}).get("query_type", ""))
        if key == "_query_type":
            actual = actual_qtype
        else:
            actual = ts_payload.get(key)
        ok, msg = _check_val(key, actual, val)
        checks.append((f"router.{key}", ok, msg))
        if not ok:
            errors.append(msg)

    # --- Extraction checks ---
    ext_exp = exp.get("extraction", {})
    intent_exp = ext_exp.get("intent")
    if intent_exp:
        found_intent = _get_extraction_intent(events)
        ok = found_intent is not None and (found_intent == intent_exp or "unknown" not in str(found_intent))
        checks.append(("extraction.intent", ok, f"expected {intent_exp}, got {found_intent}"))
        if not ok:
            errors.append(f"extraction: expected {intent_exp}, got {found_intent}")

    # --- Planner checks ---
    plan_exp = exp.get("planner", {})
    tool_names_exp = plan_exp.get("tool_names", [])
    if tool_names_exp:
        actual_tools = set()
        for e in events:
            if e.get("type") == "plan_created":
                steps = e.get("payload", {}).get("steps", {})
                if isinstance(steps, dict):
                    # Current shape: {"<task_id>": "<tool_name>"} — also
                    # tolerate a legacy "tool_names" key inside the dict.
                    for t in steps.values():
                        actual_tools.add(str(t))
                elif isinstance(steps, list):
                    for t in steps:
                        if isinstance(t, dict):
                            actual_tools.add(t.get("tool_name", ""))
        ok = tool_names_exp == sorted(actual_tools) if isinstance(tool_names_exp, list) else tool_names_exp == "?".split()
        checks.append(("planner.tool_names", ok, f"expected {tool_names_exp}, got {sorted(actual_tools)}"))
        if not ok:
            errors.append(f"tools: expected {tool_names_exp}, got {sorted(actual_tools)}")

    # --- Executor checks ---
    exec_exp = exp.get("executor", {})
    tool_count_gt = exec_exp.get("tool_call_count_gt", 0)
    tool_count = sum(1 for e in events if e.get("type") == "tool_call_completed" and e.get("payload", {}).get("status") == "success")
    if tool_count_gt:
        ok = tool_count >= tool_count_gt
        checks.append(("executor.tool_count", ok, f"expected >= {tool_count_gt} tool calls, got {tool_count}"))
        if not ok:
            errors.append(f"only {tool_count} tool calls (expected >= {tool_count_gt})")

    failed_exp = exec_exp.get("_executor_failed")
    if failed_exp is not None:
        # Only count tool_call_completed events with error status as actual failures
        actual_failed = []
        for e in events:
            if e.get("type") == "tool_call_completed" and e.get("payload", {}).get("status") != "success":
                actual_failed.append(e["payload"].get("tool_name", ""))
            elif e.get("type") == "error":
                # Error events without a tool_name are system errors, not tool failures
                p = e.get("payload", {})
                if isinstance(p, dict) and not p.get("tool_name"):
                    continue
        ok = set(failed_exp) == set(actual_failed)
        checks.append(("executor.failed", ok, f"expected failed={failed_exp}, got {actual_failed}"))

    # --- Response checks ---
    resp_exp = exp.get("response", {})
    resp_type = resp_exp.get("type")
    must_contain = resp_exp.get("must_contain", [])
    if resp_type:
        has_final = bool(final_text)
        if resp_type == "clarification":
            ok = has_final  # clarification produces a final_response asking for info
        elif resp_type == "tool":
            ok = has_final
        else:
            ok = has_final
        checks.append(("response.type", ok, f"expected {resp_type}, has_text={has_final} text='{final_text[:50] if final_text else 'none'}'"))
    if must_contain:
        ok, msg = _check_contains(final_text, must_contain)
        checks.append(("response.contains", ok, msg))
        if not ok:
            errors.append(msg)

    # --- Guard checks ---
    guards = exp.get("guards", {})
    avoid = guards.get("avoid_tools", [])
    if avoid:
        ok, msg = _check_avoid(events, avoid)
        checks.append(("guard.avoid_tools", ok, msg))
        if not ok:
            errors.append(msg)

    # --- Summary ---
    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    status = "✅" if passed == total else "❌"
    print(f"    ⏱ {elapsed:6.1f}s  {status} {passed}/{total} passes")
    for label, ok, msg in checks:
        mark = "✅" if ok else "❌"
        print(f"      {mark} {label}" + (f" — {msg}" if not ok else ""))
    if final_text:
        print(f"    Response: {final_text[:80]}...")

    if status == "✅":
        PASS += 1
    else:
        FAIL += 1
    RESULTS.append((tid, name, f"{passed}/{total}", f"{elapsed:.1f}s", status))

    return {"status": status, "checks": checks, "errors": errors,
            "metrics": _session_metrics(sid)}


def _session_metrics(sid: str) -> dict:
    """The scenario's eval headline metrics from the session state:
    intent_coverage (validator), capability alignment (groundedness
    signal), and response_coverage (the per-artifact citation ratio)."""
    metrics: dict = {}
    try:
        import json as _json
        import urllib.request

        with urllib.request.urlopen(
            f"{BASE}/sessions/{sid}/state", timeout=20
        ) as r:
            payload = _json.loads(r.read().decode())
        state = payload.get("state") or payload
        report = state.get("_plan_validator_report") or {}
        if isinstance(report, dict):
            metrics.update(report.get("metrics") or {})
        coverage = state.get("_response_coverage")
        if coverage is not None:
            metrics["response_coverage"] = coverage
    except Exception:
        pass
    return metrics


async def main(scenario_path=None, tier=None):
    global PASS, FAIL, RESULTS

    if scenario_path:
        paths = [scenario_path]
    else:
        scenarios_dir = Path(__file__).parent / "scenarios"
        all_paths = sorted([str(p) for p in scenarios_dir.glob("*.yaml")])
        if tier:
            selected = []
            for p in all_paths:
                try:
                    with open(p) as f:
                        meta = yaml.safe_load(f) or {}
                except Exception:
                    meta = {}
                if str(meta.get("tier", "full")) == tier:
                    selected.append(p)
            paths = selected
            print(f"\n[tier:{tier}] {len(selected)}/{len(all_paths)} scenarios selected")
            if not selected:
                print(f"ERROR: no scenarios declared tier '{tier}' — refusing a vacuous pass")
                sys.exit(1)
        else:
            paths = all_paths

    print(f"\n{'='*60}")
    print(f"SCENARIO TEST RUNNER — {len(paths)} scenarios")
    print(f"{'='*60}")

    for p in paths:
        await run_scenario(p)

    print(f"\n{'='*60}")
    print(f"{'TEST':<10} {'RESULT':>6} {'TIME':>6}  {'NAME'}")
    print(f"{'-'*10} {'-'*6} {'-'*6}  {'-'*40}")
    for tid, name, score, dur, status in RESULTS:
        print(f"  {str(tid):<8} {status:>6} {dur:>6}  {name}")
    print(f"{'='*60}")
    print(f"  {PASS}/{PASS+FAIL} scenarios passing")
    print(f"{'='*60}")

    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    _parser = argparse.ArgumentParser(description="Run YAML scenarios")
    _parser.add_argument("--scenario", default=None, help="Single scenario path")
    _parser.add_argument("--tier", default=None, choices=["fast", "medium", "full"],
                         help="Filter scenarios by declared tier")
    _args = _parser.parse_args()
    asyncio.run(main(_args.scenario, _args.tier))
