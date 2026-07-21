"""Start uvicorn and test a chat query, then print results."""
import subprocess, sys, time, json

log_path = r"C:\Users\Muhammad Husnain\Desktop\Nexus-Agentic-AI\srv_debug.log"

# Start uvicorn
cmd = [sys.executable, "-m", "uvicorn", "nexus.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "debug"]
log = open(log_path, "w", buffering=1)
proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
print(f"PID: {proc.pid}")
time.sleep(5)

import httpx
try:
    # Create session
    r = httpx.post("http://localhost:8000/api/v1/sessions", json={"title": "Debug"}, timeout=5)
    sid = r.json()["id"]
    print(f"Session: {sid}")

    # Stream chat - use non-streaming for debug
    r = httpx.post(f"http://localhost:8000/api/v1/sessions/{sid}/chat", json={"message": "Tell me the weather of Karachi?", "stream": False}, timeout=120)
    print(f"Status: {r.status_code}")
    data = r.json()
    print(f"Events: {len(data.get('events', []))}")
    for e in data.get('events', []):
        print(f"  {e['type']}")

except Exception as e:
    print(f"Error: {e}")

# Read log for debug messages
with open(log_path, "r") as f:
    content = f.read()
    for line in content.split("\n"):
        if "graph.node_yielded" in line or "translate.events" in line:
            print(line)

proc.terminate()
