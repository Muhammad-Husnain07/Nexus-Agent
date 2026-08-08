#!/usr/bin/env python3
"""TORTURE SUITE — ultra-aggressive mixed conversation test for Nexus Agent.

32 turns: confusion injection, state-machine torture, failure storms,
memory adversarial probes, approval abuse, mixed intents, broken tools.

Per-turn assertions + checkpoint verification + mock-state side-effect checks.
"""
import asyncio
import json
import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from nexus.config.settings import get_settings

BASE = "http://localhost:8000/api/v1"
G, R, Y, B, RS = "\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[0m"

RESULTS = {"pass": 0, "fail": 0, "warn": 0}
SID = None
ENGINE = None


async def create_session(client):
    r = await client.post(f"{BASE}/sessions", json={"title": "Torture Suite"})
    return r.json()["id"]


async def turn(client, msg, timeout=300):
    """Send a turn; return events, tools, errors, responses, approval."""
    events, tools, errors, responses = [], [], [], []
    approval = False
    t0 = time.time()
    async with client.stream("POST", f"{BASE}/sessions/{SID}/chat",
            json={"message": msg, "stream": True}, timeout=timeout) as resp:
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                events.append(line[7:])
            elif line.startswith("data: "):
                try:
                    d = json.loads(line[6:])
                    ev = events[-1] if events else ""
                    p = d.get("payload", {}) or {}
                    if ev == "final_response":
                        responses.append(p.get("text", ""))
                    elif ev == "tool_call_completed":
                        tools.append((p.get("tool_name"), p.get("status")))
                        if p.get("status") != "success":
                            errors.append(f"tool:{p.get('tool_name')}:{p.get('status')}")
                    elif ev == "error":
                        errors.append(p.get("message") or (p.get("errors") and str(p.get("errors"))[:80]) or "?")
                    elif ev == "approval_required":
                        approval = True
                except Exception:
                    pass
    return {"events": events, "tools": tools, "errors": errors,
            "responses": responses, "approval": approval,
            "elapsed": round(time.time() - t0, 1)}


def show(i, r, label=""):
    notable = [e for e in r["events"] if e not in ("node_completed", "workflow_composing_progress")]
    print(f"  T{i:02d} {label}: {notable}")
    for t in r["tools"]:
        m = G + "OK" + RS if t[1] == "success" else R + t[1] + RS
        print(f"        tool={t[0]} [{m}]")
    if r["responses"]:
        print(f"        resp: {r['responses'][-1][:90]}")
    if r["errors"]:
        print(f"        {R}ERRORS: {r['errors']}{RS}")


def verdict(label, ok, note=""):
    RESULTS["pass" if ok else "fail"] += 1
    print(f"  {G if ok else R}{'PASS' if ok else 'FAIL'}{RS} {label} {note}")


def warn(label, note=""):
    RESULTS["warn"] += 1
    print(f"  {Y}WARN{RS} {label} {note}")


async def approve():
    ar = await client_post_approve()
    return ar


async def client_post_approve():
    try:
        ar = await client.post(f"{BASE}/sessions/{SID}/approve", timeout=300)
        return ar.status_code
    except Exception as e:
        return str(e)


async def dump_wf(label):
    async with ENGINE.connect() as conn:
        r = await conn.execute(text(
            "SELECT checkpoint_id FROM checkpoints WHERE thread_id=:t ORDER BY checkpoint_id DESC LIMIT 1"
        ), {"t": SID})
        row = r.fetchone()
        if not row:
            print(f"    [cp:{label}] NO CHECKPOINT")
            return
        cp = row[0]
        r = await conn.execute(text(
            "SELECT channel, blob::text FROM checkpoint_writes WHERE thread_id=:t AND checkpoint_id=:c "
            "AND channel IN ('_active_workflow_id','_workflow_captured','_workflow_collected') ORDER BY channel"
        ), {"t": SID, "c": cp})
        rows = r.fetchall()
        wf = {}
        for ch, bl in rows:
            if ch == "_active_workflow_id":
                wf["wf"] = "ACTIVE" if bl and bl not in ("\\x", "") else "none"
            elif ch == "_workflow_captured":
                wf["captured"] = bl[:40]
            else:
                wf["collected"] = bl[:40]
        print(f"    [cp:{label}] {wf}")


async def mock_config(key):
    r = await client.get(f"http://localhost:8001/config/{key}")
    if r.status_code == 200:
        return r.json().get("value")
    return None


def cfg_bool(v):
    """Normalize a stored config value (bool or str) for assertions."""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, str):
        return v.strip().lower()
    return str(v).lower()


async def mock_dashboards():
    r = await client.get("http://localhost:8001/dashboards")
    if r.status_code == 200:
        return r.json()
    return []


async def scenario():
    global SID, client
    async with httpx.AsyncClient(timeout=30) as client:
        SID = await create_session(client)
        print(f"{B}Session: {SID}{RS}")

        # ── T1: bare greeting ────────────────────────────────────────────────
        r = await turn(client, "hey")
        show(1, r)
        verdict("T1 greeting: responds, no tools, no errors",
                len(r["responses"]) > 0 and not r["tools"] and not r["errors"])

        # ── T2: vague ambiguous intent ───────────────────────────────────────
        r = await turn(client, "I want to build something. You know, that thing with data. The banking one. You figure it out.")
        show(2, r)
        no_crash = not r["errors"]
        responded = len(r["responses"]) > 0
        verdict("T2 vague intent: no crash, response given", no_crash and responded,
                f"(errors={r['errors']})")

        # ── T3: abort-then-restart, all-info-at-once ────────────────────────
        r = await turn(client, "Actually forget it. Build a dashboard for ATM failures using banking_db and atm_failures, show error_code and amount")
        show(3, r)
        verdict("T3 all-at-once workflow: tools ran, no redundant first question",
                len(r["tools"]) > 0 and "workflow_input_required" not in r["events"] and not r["errors"],
                f"(tools={[t[0] for t in r['tools']]})")
        await dump_wf("T3")
        if r["approval"]:
            st = await client_post_approve()
            print(f"    T3 approval: {st}")
            await dump_wf("T3-approve")

        # ── T4: mid-workflow contradiction ───────────────────────────────────
        r = await turn(client, "wait no, use hr_db instead")
        show(4, r)
        verdict("T4 contradiction: no crash, state survives",
                not r["errors"], f"(errors={r['errors']})")
        await dump_wf("T4")

        # ── T5: triple-intent mixed message ──────────────────────────────────
        r = await turn(client, "Show me a dog image. Also fetch the unstable data. Also what's 2+2?")
        show(5, r)
        verdict("T5 mixed message: handled without crash",
                not r["errors"] or len(r["errors"]) <= 2,
                f"(tools={[t[0] for t in r['tools']]})")

        # ── T6: context-less 'continue' ──────────────────────────────────────
        r = await turn(client, "continue")
        show(6, r)
        verdict("T6 continue: graceful (advance or clarify)", not r["errors"])

        # ── T7: standard multi-tool DAG ──────────────────────────────────────
        r = await turn(client, "Get the columns for transactions and then query amount and status")
        show(7, r)
        verdict("T7 multi-tool DAG: >=2 tools", len(r["tools"]) >= 2,
                f"(tools={[t[0] for t in r['tools']]})")
        if r["approval"]:
            await client_post_approve()
            print("    T7 approval sent")
            await dump_wf("T7-approve")

        # ── T8: memory mid-flow ──────────────────────────────────────────────
        r = await turn(client, "What was I doing before this?")
        show(8, r)
        text8 = " ".join(r["responses"]).lower()
        verdict("T8 memory: references dashboard/ATM", "dashboard" in text8 or "atm" in text8,
                f"(resp={text8[:60]})")

        # ── T9: timeout tool ─────────────────────────────────────────────────
        r = await turn(client, "Fetch the timeout data", timeout=120)
        show(9, r)
        verdict("T9 timeout: graceful, <60s", r["elapsed"] < 60 and len(r["responses"]) > 0,
                f"(elapsed={r['elapsed']}s)")

        # ── T10: double failure message ──────────────────────────────────────
        r = await turn(client, "Fetch the unstable data and the timeout data", timeout=150)
        show(10, r)
        verdict("T10 double failure: graceful response", len(r["responses"]) > 0)

        # ── T11-13: approval abuse ───────────────────────────────────────────
        r = await turn(client, "Set maintenance_mode to true")
        show(11, r)
        verdict("T11 approval required", r["approval"])
        st = await client_post_approve()
        print(f"    T11 approve: {st}")
        await asyncio.sleep(3)
        v = await mock_config("maintenance_mode")
        verdict("T11 approved: config applied", cfg_bool(v) == "true", f"(value={v})")

        r = await turn(client, "Set maintenance_mode to false")
        show(12, r)
        verdict("T12 approval required again", r["approval"])
        st = await client_post_approve()
        print(f"    T12 approve: {st}")
        await asyncio.sleep(3)
        v = await mock_config("maintenance_mode")
        verdict("T12 approved: config flipped", cfg_bool(v) == "false", f"(value={v})")

        r = await turn(client, "Set maintenance_mode to true")
        show(13, r)
        verdict("T13 approval required third time", r["approval"])
        await client_post_approve()
        await asyncio.sleep(3)
        v = await mock_config("maintenance_mode")
        verdict("T13 approve: config true again", cfg_bool(v) == "true", f"(value={v})")

        # ── T14: knowledge ───────────────────────────────────────────────────
        r = await turn(client, "What is the capital of France?")
        show(14, r)
        text14 = " ".join(r["responses"]).lower()
        verdict("T14 knowledge: answers Paris", "paris" in text14, f"(resp={text14[:50]})")

        # ── T15-17: second workflow + cancel-then-uncancel ──────────────────
        r = await turn(client, "Now build a dashboard for web traffic")
        show(15, r)
        r2 = await turn(client, "Use analytics_db")
        show(16, r2)
        r3 = await turn(client, "Cancel that. No wait - continue with it.")
        show(17, r3)
        verdict("T17 cancel-then-uncancel: no crash", not r3["errors"])
        await dump_wf("T17")

        # ── T18: resume after confusion ──────────────────────────────────────
        r = await turn(client, "Use the web_traffic table")
        show(18, r)
        verdict("T18 resume: advances or graceful", not r["errors"])
        await dump_wf("T18")

        # ── T19: false-recall probe ──────────────────────────────────────────
        r = await turn(client, "What is my name?")
        show(19, r)
        text19 = " ".join(r["responses"]).lower()
        invented = any(n in text19 for n in ["alice", "bob", "zara", "john"])
        verdict("T19 no name invented", not invented, f"(resp={text19[:60]})")

        # ── T20: memory write ────────────────────────────────────────────────
        r = await turn(client, "My name is Zara. Remember that.")
        show(20, r)
        verdict("T20 memory write: no crash", not r["errors"])

        # ── T21: broken tools (proxy down) ───────────────────────────────────
        r = await turn(client, "Search the web for AI news and save it as a bookmark")
        show(21, r)
        verdict("T21 broken tools: graceful failure", len(r["responses"]) > 0,
                f"(errors={r['errors']})")

        # ── T22: memory recall after noise ───────────────────────────────────
        r = await turn(client, "What's my name?")
        show(22, r)
        text22 = " ".join(r["responses"]).lower()
        verdict("T22 recalls Zara", "zara" in text22, f"(resp={text22[:60]})")

        # ── T23: new workflow ────────────────────────────────────────────────
        r = await turn(client, "Build me a report for employee data")
        show(23, r)
        verdict("T23 new workflow: init or clarify, no crash", not r["errors"])

        # ── T24: deep memory: exact earlier request ──────────────────────────
        r = await turn(client, "Actually what did I ask for in the third message?")
        show(24, r)
        text24 = " ".join(r["responses"]).lower()
        verdict("T24 deep recall: ATM + banking_db", "atm" in text24 and ("banking" in text24 or "banking_db" in text24),
                f"(resp={text24[:70]})")

        # ── T25: one-word answer ─────────────────────────────────────────────
        r = await turn(client, "yes")
        show(25, r)
        verdict("T25 one-word: graceful", not r["errors"])

        # ── T26: sparse slot answer ──────────────────────────────────────────
        r = await turn(client, "the analytics_db")
        show(26, r)
        verdict("T26 sparse slot: graceful", not r["errors"])

        # ── T27: mid-flow field change ───────────────────────────────────────
        r = await turn(client, "Make it about error_code and amount")
        show(27, r)
        verdict("T27 field change: graceful", not r["errors"])

        # ── T28: high-risk delete ────────────────────────────────────────────
        r = await turn(client, "Delete that dashboard")
        show(28, r)
        verdict("T28 delete: approval or graceful decline",
                r["approval"] or len(r["responses"]) > 0)
        if r["approval"]:
            await client_post_approve()
            print("    T28 approval sent")

        # ── T29: bare cancel ─────────────────────────────────────────────────
        r = await turn(client, "cancel")
        show(29, r)
        verdict("T29 bare cancel: graceful", not r["errors"])

        # ── T30: full-session meta summary ───────────────────────────────────
        r = await turn(client, "What tools have I used in this whole conversation?")
        show(30, r)
        text30 = " ".join(r["responses"]).lower()
        named = any(t in text30 for t in ["dashboard", "config", "search", "dog", "query", "table"])
        verdict("T30 meta summary: names real tools", named, f"(resp={text30[:70]})")

        # ── T31: mixed knowledge + tool ──────────────────────────────────────
        r = await turn(client, "Tell me a joke and then check maintenance_mode")
        show(31, r)
        verdict("T31 mixed: handled", len(r["responses"]) > 0)

        # ── T32: close ───────────────────────────────────────────────────────
        r = await turn(client, "that's all, goodbye")
        show(32, r)
        verdict("T32 close: chat response", len(r["responses"]) > 0)


async def main():
    global ENGINE, client
    ENGINE = create_async_engine(get_settings().database.url)
    print(f"{B}Nexus Agent — TORTURE SUITE{RS}")
    print(f"Started: {datetime.now(UTC).isoformat()}")
    await scenario()
    await ENGINE.dispose()
    print(f"\n{B}{'='*70}{RS}")
    print(f"RESULTS: pass={G}{RESULTS['pass']}{RS} fail={R}{RESULTS['fail']}{RS} warn={Y}{RESULTS['warn']}{RS}")
    print(f"Finished: {datetime.now(UTC).isoformat()}")


if __name__ == "__main__":
    asyncio.run(main())
