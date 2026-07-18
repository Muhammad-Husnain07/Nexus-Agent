"""Tiered rate limits — per-IP, per-tenant, per-user, per-session.

Distinct limits for different endpoint groups:
- ``/chat`` / ``/agent``: high (60 requests/min)
- ``/tools``: medium (30 requests/min)
- ``/admin``: low (10 requests/min)

Keys are namespaced and backed by Redis sliding-window counters.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.db.context import get_tenant
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.rate_limiter import SlidingWindowRateLimiter

logger = __import__("structlog").get_logger("nexus.security.rate_limit")

BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}

# Tier definitions: (path_prefix, max_requests, window_s)
TIER_CONFIG: list[tuple[str, int, int]] = [
    ("/api/v1/agent", 60, 60),
    ("/api/v1/sessions", 60, 60),
    ("/api/v1/tools", 30, 60),
    ("/api/v1/admin", 10, 60),
    ("/api/v1/approvals", 30, 60),
    ("/api/v1/auth", 20, 60),
]

_DEFAULT_MAX = 30
_DEFAULT_WINDOW = 60


def _get_tier(path: str) -> tuple[int, int]:
    """Return ``(max_requests, window_s)`` for the matching tier."""
    for prefix, max_r, win in TIER_CONFIG:
        if path.startswith(prefix):
            return max_r, win
    return _DEFAULT_MAX, _DEFAULT_WINDOW


def _ip_key(ip: str, feature: str) -> str:
    return f"rl:ip:{ip}:{feature}"


def _tenant_key(tid: str, feature: str) -> str:
    return f"rl:tenant:{tid}:{feature}"


def _user_key(uid: str, feature: str) -> str:
    return f"rl:user:{uid}:{feature}"


class TieredRateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces tiered rate limits based on request path.

    For each request, up to three keys may be checked:
    1. Per-IP (global — always checked)
    2. Per-tenant (if tenant context is available)
    3. Per-user (if user is authenticated)

    The strictest tier is enforced.  Returns 429 with ``Retry-After``.
    """

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        redis = get_redis_client()
        if redis is None:
            return await call_next(request)

        max_r, win = _get_tier(request.url.path)
        limiter = SlidingWindowRateLimiter(redis)

        client_ip = request.client.host if request.client else "unknown"
        tid = get_tenant()
        uid = getattr(request.state, "user_id", None)

        # Check per-IP
        key = _ip_key(client_ip, "api")
        allowed = await limiter.acquire(key, max_requests=max_r, window_s=win, raise_on_limit=False)
        if not allowed:
            return _rate_limit_response(win)

        # Check per-tenant
        if tid is not None:
            key = _tenant_key(str(tid), "api")
            allowed = await limiter.acquire(
                key, max_requests=max_r, window_s=win, raise_on_limit=False
            )
            if not allowed:
                return _rate_limit_response(win)

        # Check per-user
        if uid is not None:
            key = _user_key(str(uid), "api")
            allowed = await limiter.acquire(
                key, max_requests=max_r, window_s=win, raise_on_limit=False
            )
            if not allowed:
                return _rate_limit_response(win)

        return await call_next(request)


def _rate_limit_response(window_s: int) -> Response:
    return Response(
        status_code=429,
        content='{"detail":"Rate limit exceeded","error_code":"RATE_LIMIT_EXCEEDED"}',
        media_type="application/json",
        headers={"Retry-After": str(window_s)},
    )
