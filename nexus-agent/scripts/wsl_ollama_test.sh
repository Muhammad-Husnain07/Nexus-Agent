#!/bin/bash
GW=$(ip route show default 2>/dev/null | awk '{print $3}')
echo "Gateway: $GW"
echo "Testing Ollama at gateway..."
curl -s --max-time 5 http://$GW:11434/api/tags 2>&1 | head -3
echo "Testing localhost..."
curl -s --max-time 5 http://localhost:11434/api/tags 2>&1 | head -3
echo "Testing 172.27.173.1..."
curl -s --max-time 5 http://172.27.173.1:11434/api/tags 2>&1 | head -3
echo "Done"
