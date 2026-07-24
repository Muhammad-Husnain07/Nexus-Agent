#!/bin/bash
export PATH="$HOME/.local/bin:$PATH"
cd /home/muhammad_husnain/nexus-agent
echo "Starting backend server..."
uv run uvicorn nexus.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
