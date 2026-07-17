"""Generate JWT and print instructions."""
from jose import jwt
from datetime import datetime, timedelta, timezone
n = datetime.now(timezone.utc)
t = jwt.encode({
    'sub': '00000000-0000-0000-0000-000000000001',
    'role': 'developer',
    'iss': 'nexus-agent',
    'iat': n,
    'exp': n + timedelta(days=30),
    'type': 'access',
    'tid': '11111111-1111-4111-8111-111111111111',
}, 'change-me-to-a-strong-random-secret', algorithm='HS256')
print(t)
