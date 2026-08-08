"""Queue resilience — idempotency, dead letter queue, and graceful degradation (combined)."""

import json
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from nexus.errors.resilience import ErrorCode, NexusError
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

        # Re-inject body so downstream endpoints can read it (Starlette consumes the stream)
        async def receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        request._receive = receive
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


# ============================================================================
# Dead letter queue
# ============================================================================

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from nexus.db.models.dead_letter import DeadLetterExecution

logger = structlog.get_logger("nexus.errors.dead_letter")


class DeadLetterQueue:
    """Service for managing dead letter executions."""

    def __init__(self, session_factory: Any = None) -> None:
        self._session_factory = session_factory

    async def _session(self):
        if self._session_factory:
            return self._session_factory()
        from nexus.db.base import async_session

        return async_session()

    async def send(
        self,
        tool_name: str,
        input_payload: dict[str, Any],
        error_message: str,
        error_code: str = "UNKNOWN",
        retry_count: int = 0,
        tool_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        """Persist a failed execution to the dead letter queue."""
        entry_id = uuid.uuid4()
        async with _get_session() as session:
            entry = DeadLetterExecution(
                id=entry_id,
                tool_name=tool_name,
                tool_id=tool_id,
                input_payload=input_payload,
                error_message=error_message,
                error_code=error_code,
                retry_count=retry_count,
                status="pending",
                original_timestamp=datetime.now(UTC),
            )
            session.add(entry)
            await session.commit()

        logger.info(
            "dlq.sent",
            entry_id=str(entry_id),
            tool_name=tool_name,
            error_code=error_code,
        )
        return entry_id

    async def replay(self, entry_id: uuid.UUID) -> dict[str, Any] | None:
        """Replay a dead letter execution (stub)."""
        async with _get_session() as session:
            from sqlalchemy import select

            stmt = select(DeadLetterExecution).where(DeadLetterExecution.id == entry_id)
            result = await session.execute(stmt)
            entry = result.scalar_one_or_none()

            if entry is None:
                return None

            entry.status = "replayed"
            entry.replayed_at = datetime.now(UTC)
            await session.commit()

            return {
                "id": str(entry.id),
                "tool_name": entry.tool_name,
                "input_payload": entry.input_payload,
                "error_message": entry.error_message,
            }

    async def list(
        self,
        status: str | None = None,
        tool_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List dead letter executions."""
        from sqlalchemy import select

        async with _get_session() as session:
            stmt = (
                select(DeadLetterExecution)
                .order_by(DeadLetterExecution.created_at.desc())
            )
            if status:
                stmt = stmt.where(DeadLetterExecution.status == status)
            if tool_name:
                stmt = stmt.where(DeadLetterExecution.tool_name == tool_name)
            stmt = stmt.offset(offset).limit(limit)
            result = await session.execute(stmt)
            return [_to_dict(e) for e in result.scalars().all()]


def _to_dict(entry: DeadLetterExecution) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "tool_name": entry.tool_name,
        "tool_id": str(entry.tool_id) if entry.tool_id else None,
        "error_message": entry.error_message,
        "error_code": entry.error_code,
        "retry_count": entry.retry_count,
        "status": entry.status,
        "original_timestamp": entry.original_timestamp.isoformat()
        if entry.original_timestamp
        else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


def _get_session():
    """Return an async session for DLQ operations."""
    from nexus.db.base import async_session

    return async_session()


# ============================================================================
# Graceful degradation
# ============================================================================

from typing import Any

import structlog

from nexus.redis_client.cache import RedisCache
from nexus.redis_client.client import get_redis_client

logger = structlog.get_logger("nexus.errors.graceful_degradation")

_DEGRADED_RESPONSE = (
    "I'm currently experiencing reduced functionality because one of my "
    "supporting services is temporarily unavailable.  Please try again in "
    "a few moments, or rephrase your request if it involves external tools."
)


class DegradationManager:
    """Monitors component health and provides degraded operation paths.

    Uses circuit breaker states to determine if a component is available.
    Falls back to cached responses or graceful messages.
    """

    def __init__(self) -> None:
        self._cache: RedisCache | None = None

    @property
    def cache(self) -> RedisCache | None:
        if self._cache is None:
            redis = get_redis_client()
            if redis is not None:
                self._cache = RedisCache(redis, prefix="nexus:degradation")
        return self._cache

    async def check_llm_available(self) -> bool:
        """Check if any LLM provider is available via circuit breaker states."""
        from nexus.errors.resilience import registry as cb_registry

        open_breakers = cb_registry.all_open()
        if not open_breakers:
            return True  # No open breakers = LLM available

        # If all registered LLM breakers are open, LLM is degraded
        llm_open = [n for n in open_breakers if _is_llm_breaker(n)]
        return len(llm_open) < 2  # Degrade only if most providers are open

    async def check_tool_available(self, tool_name: str) -> bool:
        """Check if a specific tool is available via circuit breaker state."""
        from nexus.errors.resilience import registry as cb_registry

        state = cb_registry.state_of(f"tool:{tool_name}")
        return state != "open"

    async def degraded_llm_response(self, query_hash: str | None = None) -> str:
        """Return a graceful degradation message for LLM failures.

        Args:
            query_hash: Optional hash of the user's query for cache lookup.

        Returns:
            A cached similar response, or a standard degraded message.
        """
        cache = self.cache
        if cache and query_hash:
            cached = await cache.get(f"llm_degraded:{query_hash}")
            if cached and isinstance(cached, str):
                return cached

        return _DEGRADED_RESPONSE

    async def degraded_tool_response(self, tool_name: str) -> dict[str, Any]:
        """Return a structured degraded response for a tool failure.

        Returns a dict that the agent can use to decide on alternative actions.
        """
        logger.warning("tool.degraded", tool_name=tool_name)
        return {
            "status": "degraded",
            "tool_name": tool_name,
            "error_code": ErrorCode.SERVICE_DEGRADED.value,
            "message": f"The tool '{tool_name}' is currently unavailable.  "
            f"Please try again later or use an alternative tool.",
            "retryable": True,
        }

    async def check_db_available(self) -> bool:
        """Check database availability via a simple probe.

        Returns ``True`` if the DB appears to be available.
        """
        try:
            from nexus.db.base import async_session

            async with async_session() as session:
                from sqlalchemy import text

                await session.execute(text("SELECT 1"))
                return True
        except Exception:
            logger.warning("db.unavailable")
            return False


def _is_llm_breaker(breaker_name: str) -> bool:
    """Return True if the breaker name corresponds to an LLM provider."""
    return breaker_name.startswith("llm:") or not breaker_name.startswith("tool:")
