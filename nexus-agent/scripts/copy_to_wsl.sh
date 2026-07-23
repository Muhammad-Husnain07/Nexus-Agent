#!/bin/bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
MYDIR="/mnt/c/Users/Muhammad Husnain/Desktop/Nexus-Agentic-AI/nexus-agent"
DEST="$HOME/nexus-agent"

echo "Creating destination..."
mkdir -p "$DEST"
echo "Copying files (excluding .venv)..."
rsync -av --exclude=.venv --exclude=__pycache__ --exclude=.git --exclude=.mypy_cache --exclude=.ruff_cache --exclude=.pytest_cache "$MYDIR/" "$DEST/" 2>&1 | tail -3

echo "Setting up venv..."
cd "$DEST"
python3.14 -m venv .venv
source .venv/bin/activate
uv sync --frozen 2>&1 | tail -5

echo "Testing Ollama..."
curl -s --max-time 5 http://host.docker.internal:11434/api/tags > /dev/null && echo "Ollama via host.docker.internal: OK" || echo "Ollama via host.docker.internal: FAIL"
curl -s --max-time 5 http://172.17.0.1:11434/api/tags > /dev/null && echo "Ollama via 172.17.0.1: OK" || echo "Ollama via 172.17.0.1: FAIL"

echo "Setup complete"
