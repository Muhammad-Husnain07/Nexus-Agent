#!/bin/bash
# Complex test suite - shell script for reliable WSL2 execution
# Tests: chaining, parallelism, cross-turn memory, multi-tool, pure conversation
set -e

cd /home/muhammad_husnain/nexus-agent
pkill -f "uvicorn nexus.main" 2>/dev/null || true
sleep 2

RESTCOUNTRIES_API_KEY=rc_live_demo /home/muhammad_husnain/nexus-agent/.venv/bin/python -m uvicorn nexus.main:create_app --factory --host 0.0.0.0 --port 8000 > /tmp/server.log 2>&1 &
SERVER_PID=$!

# Wait for server
for i in $(seq 1 30); do
    sleep 1
    if curl -s http://localhost:8000/healthz > /dev/null 2>&1; then
        echo "READY"
        break
    fi
done

# Create session
curl -s -X POST http://localhost:8000/api/v1/sessions -H "Content-Type: application/json" -d '{}' > /tmp/session.json
SID=$(python3 -c "import json; print(json.load(open('/tmp/session.json'))['id'])")
echo "Session: $SID"

TOTAL=0
PASSED=0

run_test() {
    local query="$1"
    local desc="$2"
    local expected_min_chars="$3"
    TOTAL=$((TOTAL + 1))
    echo ""
    echo "=== Test $TOTAL: $desc ==="
    echo "Query: $query"
    
    curl -s -m 120 -X POST "http://localhost:8000/api/v1/sessions/$SID/chat" \
        -H "Content-Type: application/json" \
        -d "{\"message\":\"$query\",\"stream\":false}" > /tmp/test_resp.json 2>/dev/null
    
    local resp_len=$(python3 -c "import json; d=json.load(open('/tmp/test_resp.json')); print(len(d.get('final_response','') or ''))")
    local resp_text=$(python3 -c "import json; d=json.load(open('/tmp/test_resp.json')); print((d.get('final_response','') or '')[:150])")
    local err_count=$(python3 -c "import json; d=json.load(open('/tmp/test_resp.json')); es=[e for e in d.get('events',[]) if e['type']=='error']; print(len(es))")
    local tool_success=$(python3 -c "import json; d=json.load(open('/tmp/test_resp.json')); ts=[e for e in d.get('events',[]) if e['type']=='tool_call_completed' and e['payload'].get('status')=='success']; print(len(ts))")
    local node_count=$(python3 -c "import json; d=json.load(open('/tmp/test_resp.json')); ns=set(e['payload'].get('node','') for e in d.get('events',[]) if e['type']=='node_completed'); print(len(ns))")
    
    echo "Response: ${resp_len} chars - ${resp_text}..."
    echo "Tools succeeded: ${tool_success} | Errors: ${err_count} | Nodes: ${node_count}"
    
    if [ "$resp_len" -ge "$expected_min_chars" ] && [ "$err_count" -eq "0" ]; then
        echo "PASS"
        PASSED=$((PASSED + 1))
    else
        if [ "$resp_len" -lt "$expected_min_chars" ]; then
            echo "FAIL: Response too short (${resp_len} < ${expected_min_chars})"
        fi
        if [ "$err_count" -ne "0" ]; then
            echo "FAIL: ${err_count} error events"
        fi
    fi
}

# Run tests
run_test "What is the weather in Tokyo and tell me a joke" "Weather chain + joke" 100
run_test "What about the weather in Paris and get a cat fact too" "Follow-up + cat fact" 100
run_test "Tell me about Pikachu and what country is Japan?" "Pokemon + country" 100
run_test "What was the temperature in Tokyo earlier and show me a dog image" "Memory recall + dog" 30
run_test "Compare Japan and Canada - which is larger and what are their capitals?" "Cross-reference comparison" 100
run_test "Give me a random user and a book about machine learning" "Parallel user + books" 100
run_test "What was the name of the random user and the book title from before?" "Pure memory recall" 30

# Summary
echo ""
echo "=== RESULTS ==="
echo "Passed: $PASSED / $TOTAL"
if [ "$PASSED" -eq "$TOTAL" ]; then
    echo "ALL TESTS PASSED"
else
    echo "SOME TESTS FAILED"
    exit 1
fi

# Cleanup
kill $SERVER_PID 2>/dev/null || true
