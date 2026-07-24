#!/bin/bash
SID=$(curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H 'Content-Type: application/json' -d '{}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "Session: $SID"

echo ""
echo "=== TEST 1: Simple Query (joke) ==="
curl -s -X POST "http://localhost:8000/api/v1/sessions/$SID/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Tell me a joke"}'
echo ""

echo ""
echo "=== TEST 2: Independent Multi (weather + joke) ==="
SID2=$(curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H 'Content-Type: application/json' -d '{}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "Session: $SID2"
curl -s -X POST "http://localhost:8000/api/v1/sessions/$SID2/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Whats the weather in Lahore and tell me a joke"}'
echo ""

echo ""
echo "=== TEST 3: Dependent Multi (geocode then weather) ==="
SID3=$(curl -s -X POST http://localhost:8000/api/v1/sessions \
  -H 'Content-Type: application/json' -d '{}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "Session: $SID3"
curl -s -X POST "http://localhost:8000/api/v1/sessions/$SID3/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Whats the weather in Lahore"}'
echo ""

echo "=== DONE ==="
