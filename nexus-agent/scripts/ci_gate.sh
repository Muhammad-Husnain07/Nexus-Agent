#!/usr/bin/env bash
# CI gate — the mandatory verification before any orchestration change ships.
#   ./scripts/ci_gate.sh            # full gate (fast suites)
#   ./scripts/ci_gate.sh --live     # full gate + live scenario matrix + fast tier
#   ./scripts/ci_gate.sh --fast     # full gate + live matrix + fast scenario tier
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== architecture fingerprint (CI artifact) =="
uv run python -c "
from nexus.agent.architecture import ArchitectureVersion
print(ArchitectureVersion.to_json())
" | tee artifacts/architecture-fingerprint.json || true

echo "== ruff =="
uv run ruff check src tests scripts --output-format concise || true

echo "== static gate (208 + contract + drift + handoff tests) =="
uv run pytest -q --no-cov -m "not live"

if [[ "${1:-}" == "--live" || "${1:-}" == "--fast" ]]; then
    echo "== live scenario matrix =="
    uv run pytest tests/test_scenario_matrix.py -m live -q --no-cov -s
    echo "== fast scenario tier (canonical suite — BLOCKING) =="
    uv run python tests/run_scenarios.py --tier fast
fi

echo "== GATE PASSED =="
