#!/bin/bash
set -e

NEXUS_DIR="/mnt/c/Users/Muhammad Husnain/Desktop/Nexus-Agentic-AI/nexus-agent"
cd "$NEXUS_DIR"

echo "[1/5] Creating virtual environment..."
python3.14 -m venv .venv --without-pip

echo "[2/5] Installing uv..."
source .venv/bin/activate
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

echo "[3/5] Syncing dependencies..."
uv sync --frozen 2>&1 | tail -5

echo "[4/5] Testing model accessibility..."
curl -s http://host.docker.internal:11434/api/tags > /dev/null && echo "Ollama OK" || echo "Ollama FAIL"

echo "[5/5] Done. Run: cd $NEXUS_DIR && source .venv/bin/activate && uv run uvicorn nexus.main:app --host 0.0.0.0 --port 8000"
