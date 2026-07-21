"""Tiered rate limits — per-IP sliding window rate limiter.

Uses Redis Sorted Sets for accurate sliding-window accounting.
Gracefully degrades (allows request) when Redis is unavailable.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from nexus.redis_client.client import get_redis_client
from nexus.redis_client.rate_limiter import SlidingWindowRateLimiter

logger = structlog.get_logger("nexus.security.rate_limit")

DEFAULT_MAX_REQUESTS = 100
DEFAULT_WINDOW_S = 60


class TieredRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window rate limiter with Redis fallback.

    Rates:
    1. Per-IP base rate (100 req / 60s).
    2. Per-feature (if available).
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._feature_limits: dict[str, tuple[int, int]] = {
            "chat": (30, 60),
            "tools": (60, 60),
        }

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        redis = get_redis_client()
        if redis is None:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        try:
            # Per-IP rate limit
            ip_key = f"rl:ip:{client_ip}"
            limiter = SlidingWindowRateLimiter(redis)
            ip_allowed = await limiter.acquire(ip_key, max_requests=DEFAULT_MAX_REQUESTS, window_s=DEFAULT_WINDOW_S)
            if not ip_allowed:
                logger.warning("rate_limit.exceeded", client_ip=client_ip)
                return Response(
                    status_code=429,
                    content='{"detail":"Rate limit exceeded","error_code":"RATE_LIMITED"}',
                    media_type="application/json",
                    headers={"Retry-After": "60"},
                )

            # Per-feature rate limit based on path prefix
            path = request.url.path
            for feature, (max_r, window) in self._feature_limits.items():
                if f"/{feature}" in path:
                    feature_key = f"rl:feature:{feature}:{client_ip}"
                    feature_limiter = SlidingWindowRateLimiter(redis)
                    feature_allowed = await feature_limiter.acquire(feature_key, max_requests=max_r, window_s=window)
                    if not feature_allowed:
                        logger.warning("rate_limit.feature_exceeded", feature=feature, client_ip=client_ip)
                        return Response(
                            status_code=429,
                            content=f'{{"detail":"{feature} rate limit exceeded","error_code":"RATE_LIMITED"}}',
                            media_type="application/json",
                            headers={"Retry-After": str(window)},
                        )
                    break

        except Exception:
            logger.warning("rate_limit.check_failed", exc_info=True)

        return await call_next(request)
