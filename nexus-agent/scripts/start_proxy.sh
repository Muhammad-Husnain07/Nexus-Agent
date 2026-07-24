#!/bin/bash
export PATH="/home/muhammad_husnain/.local/bin:$PATH"
cd /home/muhammad_husnain/nexus-agent
uv run python scripts/web_search_server.py > /tmp/web_search_server.log 2>&1 &
echo "PID: $!"
sleep 3
curl -s http://localhost:8081/search?q=hello | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Status OK: {d[\"result_count\"]} results for \"{d[\"query\"]}\"')"
