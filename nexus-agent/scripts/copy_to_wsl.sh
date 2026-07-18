#!/usr/bin/env bash
SRC="/mnt/c/Users/Muhammad Husnain/Desktop/Nexus-Agentic-AI"
DST="$HOME/nexus-agent"
cp "$SRC/src/nexus/llm/provider.py" "$DST/src/nexus/llm/provider.py"
cp "$SRC/src/nexus/llm/client.py" "$DST/src/nexus/llm/client.py"
echo COPIED
