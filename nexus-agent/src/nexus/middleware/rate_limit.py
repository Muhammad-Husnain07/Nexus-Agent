"""Per-tenant rate limiting middleware using Redis sliding window."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.db.context import get_tenant
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.rate_limiter import SlidingWindowRateLimiter, tenant_key

BYPASS_PATHS = {"/healthz", "/readyz", "/docs", "/redoc", "/openapi.json"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter keyed by tenant ID.

    Enforces ``max_requests`` per ``window_s`` per tenant.  Returns 429
    with a ``Retry-After`` header when the limit is exceeded.

    The limits can be configured via ``Tenant.settings["rate_limit"]``.
    Falls back to a safe default if not configured or if Redis is down.
    """

    def __init__(self, app, max_requests: int = 200, window_s: int = 60, **kwargs):  # noqa: PLR0913
        super().__init__(app, **kwargs)
        self._max_requests = max_requests
        self._window_s = window_s

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        if request.url.path in BYPASS_PATHS:
            return await call_next(request)

        tenant_id = get_tenant()
        if tenant_id is None:
            return await call_next(request)

        redis = get_redis_client()
        if redis is None:
            return await call_next(request)

        limiter = SlidingWindowRateLimiter(redis)
        key = tenant_key(tenant_id, "api")
        allowed = await limiter.acquire(
            key,
            max_requests=self._max_requests,
            window_s=self._window_s,
            raise_on_limit=False,
        )

        if not allowed:
            return Response(
                status_code=429,
                content='{"detail":"Rate limit exceeded","error_code":"RATE_LIMIT_EXCEEDED"}',
                media_type="application/json",
                headers={"Retry-After": str(self._window_s)},
            )

        return await call_next(request)
