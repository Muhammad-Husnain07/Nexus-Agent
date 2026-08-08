#!/usr/bin/env python3
"""Scenario Stability Score — tracks scenario health over repeated runs.

For each scenario in a tier, runs it N times and records per-scenario:
pass rate, flaky rate (mixed results across attempts), mean latency,
planner accuracy, tool accuracy, and response accuracy. History persists
to a JSON file; a scenario is HEALTHY only after ``--healthy-window``
consecutive clean runs (never after a single pass).

Usage:
    uv run python scripts/stability_score.py --tier fast --runs 3
    uv run python scripts/stability_score.py --tier full --runs 5
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "tests" / "scenarios"
RUNNER_PATH = Path(__file__).resolve().parent.parent / "tests" / "run_scenarios.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_scenarios", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _scenarios_for_tier(runner, tier: str | None) -> list[Path]:
    paths = sorted(SCENARIOS_DIR.glob("*.yaml"))
    if not tier:
        return paths
    selected = []
    for p in paths:
        try:

            meta = yaml.safe_load(p.read_text()) or {}
        except Exception:
            meta = {}
        if str(meta.get("tier", "full")) == tier:
            selected.append(p)
    return selected


def _label_accuracy(checks: list, prefix: str) -> float:
    matching = [(ok, msg) for label, ok, msg in checks if label.startswith(prefix)]
    if not matching:
        return float("nan")
    return sum(1 for ok, _ in matching for ok in [ok]) / len(matching)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scenario stability score")
    parser.add_argument("--tier", choices=["fast", "medium", "full"], default=None)
    parser.add_argument("--runs", type=int, default=3, help="Attempts per scenario")
    parser.add_argument("--healthy-window", type=int, default=3,
                        help="Consecutive clean runs required for healthy")
    parser.add_argument("--history", default="tests/stability_history.json")
    args = parser.parse_args()

    runner = _load_runner()
    paths = _scenarios_for_tier(runner, args.tier)
    history_path = Path(__file__).resolve().parent.parent / args.history
    history: dict = {}
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
        except Exception:
            history = {}

    print(f"stability: {len(paths)} scenarios x {args.runs} runs "
          f"(healthy window {args.healthy_window})")
    print(f"{'tid':<8} {'pass':>4} {'flaky':>5} {'mean_ms':>8} {'planner':>7} "
          f"{'tool':>7} {'resp':>7}  status")

    for path in paths:
        try:

            meta = yaml.safe_load(path.read_text()) or {}
        except Exception:
            meta = {}
        tid = meta.get("test_id", path.stem)
        name = meta.get("name", path.stem)
        attempts = []
        for _ in range(args.runs):
            runner.PASS = 0
            runner.FAIL = 0
            runner.RESULTS = []
            t0 = time.perf_counter()
            try:
                outcome = asyncio.run(runner.run_scenario(str(path)))
                elapsed_ms = (time.perf_counter() - t0) * 1000
            except Exception as exc:
                outcome = {"status": "❌", "checks": [], "errors": [str(exc)]}
                elapsed_ms = (time.perf_counter() - t0) * 1000
            checks = outcome.get("checks", [])
            total = len(checks) or 1
            passed = sum(1 for _, ok, _ in checks if ok)
            _m = outcome.get("metrics") or {}
            attempts.append({
                "ts": datetime.now(UTC).isoformat(),
                "status": outcome.get("status", "❌"),
                "passed_checks": passed,
                "total_checks": total,
                "elapsed_ms": round(elapsed_ms, 1),
                "intent_coverage": _m.get("intent_coverage"),
                "response_coverage": _m.get("response_coverage"),
                "capability_alignment": _m.get("capability_alignment"),
            })
        history[str(tid)] = history.get(str(tid), []) + attempts

        recent = history[str(tid)][-args.healthy_window:]
        pass_rate = sum(1 for a in attempts if a["status"] == "✅") / len(attempts)
        flaky = 0 < pass_rate < 1.0
        mean_ms = round(sum(a["elapsed_ms"] for a in attempts) / len(attempts), 1)
        healthy = len(recent) >= args.healthy_window and all(
            a["status"] == "✅" for a in recent
        )
        status = "HEALTHY" if healthy else ("FLAKY" if flaky else "watching")
        planner_acc = _label_accuracy(checks, "planner.")
        tool_acc = _label_accuracy(checks, "executor.")
        resp_acc = _label_accuracy(checks, "response.")
        _cov = [a.get("response_coverage") for a in attempts if a.get("response_coverage") is not None]
        _icov = [a.get("intent_coverage") for a in attempts if a.get("intent_coverage") is not None]
        mean_resp_cov = round(sum(_cov) / len(_cov), 2) if _cov else float("nan")
        mean_intent_cov = round(sum(_icov) / len(_icov), 2) if _icov else float("nan")
        print(
            f"{str(tid):<8} {pass_rate:>4.0%} {str(flaky):>5} {mean_ms:>8.1f} "
            f"{planner_acc:>7.0%} {tool_acc:>7.0%} {resp_acc:>7.0%} "
            f"cov:{mean_intent_cov:>4.2f} resp:{mean_resp_cov:>4.2f}  {status} "
            f"({name[:30]})"
        )

    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=1))
    print(f"\nhistory -> {history_path} ({sum(len(v) for v in history.values())} attempts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
