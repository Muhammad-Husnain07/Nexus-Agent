#!/bin/bash
SID=$(cat /proc/sys/kernel/random/uuid)
echo "Session: $SID"
echo ""

echo "=== T1: Hi ==="
curl -s -X POST http://localhost:8000/api/v1/sessions/$SID/chat -H 'Content-Type: application/json' -d '{"message":"Hi","stream":false}' --max-time 60 | python3 -c "import sys,json;d=json.load(sys.stdin);print('R:',(d.get('final_response')or'')[:60])"
echo ""

echo "=== T2: Joke ==="
curl -s -X POST http://localhost:8000/api/v1/sessions/$SID/chat -H 'Content-Type: application/json' -d '{"message":"Tell me a joke","stream":false}' --max-time 120 | python3 -c "import sys,json;d=json.load(sys.stdin);print('R:',(d.get('final_response')or'')[:80])"
echo ""

echo "=== T3: Cat + Tokyo Weather ==="
curl -s -X POST http://localhost:8000/api/v1/sessions/$SID/chat -H 'Content-Type: application/json' -d '{"message":"Tell me a fact about a cat and Also Japan Capital Weather.","stream":false}' --max-time 300 | python3 -c "import sys,json;d=json.load(sys.stdin);print('R:',(d.get('final_response')or'')[:150])"
echo ""

echo "=== DONE ==="
