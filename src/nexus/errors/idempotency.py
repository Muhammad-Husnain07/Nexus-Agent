"""Idempotency-Key header support — Redis-backed response cache for 24h.

When a client sends an ``Idempotency-Key`` header with a ``POST`` request,
the response is cached for 24 hours.  If the same key is sent again within
that window, the cached response is returned (idempotent replay).
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from nexus.errors.base import ErrorCode, NexusError
from nexus.redis_client.client import get_redis_client

logger = structlog.get_logger("nexus.errors.idempotency")

IDEMPOTENCY_TTL_S = 86400  # 24 hours
IDEMPOTENCY_HEADER = "Idempotency-Key"


class IdempotencyConflict(NexusError):
    """Raised when an Idempotency-Key is reused with a different request body."""

    def __init__(self, key: str) -> None:
        super().__init__(
            code=ErrorCode.IDEMPOTENCY_CONFLICT,
            message=f"Idempotency-Key '{key}' already exists with a different request",
            status_code=409,
        )


async def cache_idempotent_response(
    key: str,
    status_code: int,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    ttl_s: int = IDEMPOTENCY_TTL_S,
) -> None:
    """Store a response in the idempotency cache."""
    redis = get_redis_client()
    if redis is None:
        return

    payload = json.dumps(
        {
            "status_code": status_code,
            "body": body,
            "headers": headers or {},
        }
    )
    await redis.set(f"idempotency:{key}", payload, ex=ttl_s)


async def get_idempotent_response(key: str) -> dict[str, Any] | None:
    """Retrieve a cached idempotent response."""
    redis = get_redis_client()
    if redis is None:
        return None

    raw = await redis.get(f"idempotency:{key}")
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


async def try_lock_idempotency_key(key: str, request_body: str, ttl_s: int = 30) -> bool:
    """Atomically claim an idempotency key.

    Returns ``True`` if the key was claimed (first request).
    Returns ``False`` if the key already exists (duplicate).
    Raises ``IdempotencyConflict`` if the key exists with a different body.
    """
    redis = get_redis_client()
    if redis is None:
        return True  # No Redis = no dedup protection, allow through

    lock_key = f"idempotency_lock:{key}"
    existing = await redis.get(lock_key)
    if existing is not None:
        if existing.decode("utf-8") != request_body:
            raise IdempotencyConflict(key)
        return False  # Duplicate — caller should return cached response

    await redis.set(lock_key, request_body, ex=ttl_s)
    return True


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that handles ``Idempotency-Key`` header.

    For ``POST`` requests with an ``Idempotency-Key``:
    1. Check if a cached response exists → return it immediately.
    2. Lock the key (prevent concurrent duplicates).
    3. Let the request proceed normally.
    4. On success response, cache it under the key.
    """

    async def dispatch(self, request: Request, call_next: callable) -> Response:
        if request.method != "POST":
            return await call_next(request)

        idem_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not idem_key:
            return await call_next(request)

        # Check for cached response
        cached = await get_idempotent_response(idem_key)
        if cached is not None:
            logger.info("idempotency.cache_hit", key=idem_key)
            return JSONResponse(
                status_code=cached["status_code"],
                content=cached["body"],
                headers=cached.get("headers"),
            )

        # Lock the key (ensures first-writer wins)
        body_bytes = await request.body()
        body_text = body_bytes.decode("utf-8", errors="replace")
        try:
            is_new = await try_lock_idempotency_key(idem_key, body_text)
        except IdempotencyConflict as exc:
            return JSONResponse(
                status_code=409, content={"error": {"code": exc.code.value, "message": exc.message}}
            )

        if not is_new:
            # Duplicate with same body — fall back to cache check after lock released
            cached = await get_idempotent_response(idem_key)
            if cached:
                return JSONResponse(
                    status_code=cached["status_code"],
                    content=cached["body"],
                    headers=cached.get("headers"),
                )

        # Process the request
        response = await call_next(request)

        # Cache successful responses
        if 200 <= response.status_code < 300:
            response_body = await _extract_response_body(response)
            if response_body is not None:
                resp_headers = dict(response.headers) if hasattr(response, "headers") else {}
                await cache_idempotent_response(
                    idem_key, response.status_code, response_body, resp_headers
                )

        return response


async def _extract_response_body(response: Any) -> dict[str, Any] | None:
    """Extract JSON body from a response for caching."""
    if hasattr(response, "body") and response.body:
        try:
            return json.loads(response.body)
        except (json.JSONDecodeError, TypeError):
            return None
    if hasattr(response, "body_iterator") and response.body_iterator:
        chunks = [chunk async for chunk in response.body_iterator]
        text = b"".join(chunks).decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
    return None
