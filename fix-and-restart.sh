#!/bin/bash
cp "/mnt/c/Users/Muhammad Husnain/Desktop/Nexus-Agentic-AI/nexus-agent/src/nexus/agent/state_schema.py" /home/muhammad_husnain/nexus-agent/src/nexus/agent/state_schema.py
cp "/mnt/c/Users/Muhammad Husnain/Desktop/Nexus-Agentic-AI/nexus-agent/src/nexus/agent/runner.py" /home/muhammad_husnain/nexus-agent/src/nexus/agent/runner.py
tmux kill-session -t nx 2>/dev/null
tmux new-session -d -s nx /home/muhammad_husnain/start-backend.sh
echo "Done"
