#!/bin/bash
export PATH="$HOME/.local/bin:$PATH"
cd /mnt/c/Users/Muhammad*/Desktop/Nexus-Agentic-AI/nexus-agent
source .venv/bin/activate
echo "uv version: $(uv --version 2>&1)"
uv sync --frozen 2>&1 | tail -5
echo "Sync complete"
