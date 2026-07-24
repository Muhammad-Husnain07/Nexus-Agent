#!/bin/bash
export PATH="/home/muhammad_husnain/.local/bin:$PATH"
cd /home/muhammad_husnain/nexus-agent
uv run python scripts/web_search_server.py > /tmp/web_search_server.log 2>&1 &
PROXY_PID=$!
echo "Proxy PID: $PROXY_PID"
sleep 3
if curl -sf http://localhost:8081/search?q=healthcheck > /dev/null 2>&1; then
    echo "Proxy server OK on port 8081"
else
    echo "Proxy server FAILED - check /tmp/web_search_server.log"
    cat /tmp/web_search_server.log
fi
