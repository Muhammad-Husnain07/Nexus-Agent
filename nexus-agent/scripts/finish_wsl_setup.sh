#!/bin/bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
cd ~/nexus-agent || exit 1
rm -rf .venv
echo "Creating venv..."
python3.14 -m venv .venv
source .venv/bin/activate
echo "Syncing deps..."
uv sync --frozen 2>&1 | tail -3
echo "Testing Ollama..."
curl -s --max-time 5 http://host.docker.internal:11434/api/generate -d '{"model":"qwen2.5:7b","prompt":"hi","stream":false}' > /dev/null 2>&1 && echo "Ollama OK" || echo "Ollama FAIL"
echo "Ready"
