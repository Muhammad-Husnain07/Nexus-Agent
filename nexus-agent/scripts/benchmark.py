"""Latency benchmark harness — stage percentages from _stage_metrics.

Usage:
    python scripts/benchmark.py            # runs the 4 core scenarios
    python scripts/benchmark.py --json     # machine-readable output

Reads the live API's per-turn ``_stage_metrics`` (node → ms) and prints the
total + per-stage share per scenario, so optimization is measurement-driven.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

BASE = "http://localhost:8000/api/v1"

SCENARIOS = {
    "single-tool": ["How's the temperature in Tokyo?"],
    "sequential": ["How's the temperature in Tokyo?", "And in Osaka?"],
    "parallel": ["List Studio Ghibli films and list Valorant agents"],
    "workflow": ["I need a weather briefing", "Tokyo"],
}


def _post(url: str, payload: dict, timeout: int = 700) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _run(sid: str, message: str) -> dict:
    return _post(f"{BASE}/sessions/{sid}/chat", {
        "session_id": sid, "message": message, "stream": False,
    })


def _stage_metrics(resp: dict) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for ev in resp.get("events") or []:
        if ev["type"] == "node_completed":
            node = ev["payload"].get("node")
            duration = ev["payload"].get("duration_ms", 0) or 0
            metrics[node] = metrics.get(node, 0.0) + float(duration)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Orchestration latency benchmark")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    try:
        from nexus.agent.architecture import ArchitectureVersion

        arch_fingerprint = ArchitectureVersion.cache_fingerprint()
        arch_manifest = ArchitectureVersion.to_json()
    except Exception:
        arch_fingerprint = "unknown"
        arch_manifest = "{}"

    report: dict[str, dict] = {"architecture": {
        "fingerprint": arch_fingerprint,
        "manifest": json.loads(arch_manifest),
    }}
    for name, messages in SCENARIOS.items():
        sid = _post(f"{BASE}/sessions", {"session_name": f"bench-{name}"})["id"]
        per_turn: list[dict] = []
        for msg in messages:
            t0 = time.perf_counter()
            resp = _run(sid, msg)
            wall = (time.perf_counter() - t0) * 1000
            per_turn.append({
                "message": msg[:40],
                "wall_ms": round(wall, 1),
                "stages": _stage_metrics(resp),
            })
        total_stages: dict[str, float] = {}
        for turn in per_turn:
            for node, ms in turn["stages"].items():
                total_stages[node] = total_stages.get(node, 0.0) + ms
        total = sum(total_stages.values()) or 1.0
        shares = {
            node: round(ms / total * 100, 1)
            for node, ms in sorted(total_stages.items(), key=lambda x: x[1], reverse=True)
        }
        report[name] = {
            "total_stage_ms": round(total, 1),
            "wall_ms": round(sum(t["wall_ms"] for t in per_turn), 1),
            "stage_shares_pct": shares,
        }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"\narchitecture fingerprint: {arch_fingerprint}")
    for name, data in report.items():
        if name == "architecture":
            continue
        print(f"\n[{name}] stage total {data['total_stage_ms']:.0f}ms / wall {data['wall_ms']:.0f}ms")
        for node, pct in data["stage_shares_pct"].items():
            print(f"  {node:24s} {pct:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
