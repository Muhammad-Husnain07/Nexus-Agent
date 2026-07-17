"""Test chat directly."""
import urllib.request, json, sys
from jose import jwt
from datetime import datetime, timedelta, timezone

t = jwt.encode({
    'sub': '00000000-0000-0000-0000-000000000001',
    'role': 'developer',
    'iss': 'nexus-agent',
    'iat': datetime.now(timezone.utc),
    'exp': datetime.now(timezone.utc) + timedelta(days=30),
    'type': 'access',
    'tid': '11111111-1111-4111-8111-111111111111',
}, 'change-me-to-a-strong-random-secret', algorithm='HS256')

h = {"Authorization":f"Bearer {t}","Content-Type":"application/json","X-Tenant-ID":"11111111-1111-4111-8111-111111111111"}

# Create session
r = urllib.request.Request("http://localhost:8000/api/v1/sessions", data=b'{"title":"test"}', headers=h, method="POST")
resp = urllib.request.urlopen(r, timeout=10)
sid = json.loads(resp.read())["id"]
print(f"Session: {sid}")

# Send message (non-streaming)
msg = json.dumps({"message":"List articles in Tech category","stream":False}).encode()
r = urllib.request.Request(f"http://localhost:8000/api/v1/sessions/{sid}/chat", data=msg, headers=h, method="POST")
resp = urllib.request.urlopen(r, timeout=120)
data = json.loads(resp.read())
fr = data.get("final_response","(none)")
print(f"Final: {fr[:300] if fr else 'None'}")
err = data.get("error")
if err:
    print(f"Error: {err[:200]}")
print(f"Events: {len(data.get('events',[]))}")
