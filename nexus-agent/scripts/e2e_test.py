"""End-to-end test of the agent with tool calling."""
import json
import urllib.request
import uuid
import sys

sid = str(uuid.uuid4())
print(f"Session: {sid}")

req = urllib.request.Request(
    f'http://127.0.0.1:8000/api/v1/sessions/{sid}/chat',
    data=json.dumps({'message': 'list all tags', 'stream': False}).encode(),
    headers={
        'Content-Type': 'application/json',
        'X-Tenant-ID': '11111111-1111-4111-8111-111111111111',
    },
    method='POST',
)

try:
    resp = urllib.request.urlopen(req, timeout=180)
    data = json.loads(resp.read())
    print(f"Final: {data.get('final_response', 'None')[:200]}")
    print(f"Events: {[e['type'] for e in data.get('events', [])]}")
    print(f"Errors: {data.get('error')}")
    if data.get('error'):
        print("❌ TEST FAILED")
        sys.exit(1)
    print("✅ TEST PASSED")
except urllib.error.HTTPError as e:
    print(f"❌ HTTP Error {e.code}: {e.read().decode()[:200]}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Exception: {e}")
    sys.exit(1)
