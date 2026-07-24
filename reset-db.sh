#!/bin/bash
export PATH="$HOME/.local/bin:$PATH"
cd /home/muhammad_husnain/nexus-agent
uv run python /tmp/reset_db.py
