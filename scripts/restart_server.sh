#!/usr/bin/env bash
# Restart the Nexus Agent server in a tmux session
set -euo pipefail
tmux kill-session -t nexus 2>/dev/null || true
sleep 1
cd "$HOME/nexus-agent"
tmux new-session -d -s nexus ".venv/bin/uvicorn nexus.main:create_app --factory --workers 1 --host 0.0.0.0 --port 8000"
echo "SERVER_STARTED"
