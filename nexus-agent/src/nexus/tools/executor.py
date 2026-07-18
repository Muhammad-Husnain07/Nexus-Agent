"""ToolExecutor — performs outbound HTTP calls for tool invocations.

The executor is the only component that touches external APIs. It enforces
auth injection, input/output schema validation, retries, sandbox, approval
gating, and persistence.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import httpx
import jsonschema
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config.secrets import EnvSecretResolver, SecretResolver
from nexus.config.settings import get_settings
from nexus.db.models.tool import ToolExecution
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus, tool_channel
from nexus.redis_client.rate_limiter import RateLimitError, TokenBucketRateLimiter
from nexus.tools.approval_gate import ApprovalRequiredInterrupt, check_approval_required
from nexus.tools.result import ToolResult
from nexus.tools.retries import http_retry_policy, is_retryable_status, parse_retry_after
from nexus.tools.sandbox import (
    SandboxBlockedError,
    SandboxConfig,
    check_allowed_host,
    mask_sensitive_fields,
)
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.tools.executor")

AUTH_HEADERS: dict[str, str] = {
    "bearer": "Bearer",
    "basic": "Basic",
    "api_key": "X-API-Key",
    "oauth2": "Bearer",
}


class ExecutionContext:
    """Context for a single tool execution."""

    def __init__(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        agent_run_id: uuid.UUID | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.session_id = session_id
        self.agent_run_id = agent_run_id


class ToolExecutor:
    """Async tool executor with auth, validation, retries, and observability."""

    def __init__(
        self,
        secret_resolver: SecretResolver | None = None,
        event_bus: EventBus | None = None,
        sandbox_config: SandboxConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secret_resolver = secret_resolver or EnvSecretResolver()
        settings = get_settings()
        redis_client = get_redis_client()
        self._event_bus = event_bus or (
            EventBus(redis_client) if redis_client is not None else None
        )
        self._sandbox_config = sandbox_config or SandboxConfig(
            enabled=settings.tools.sandbox_enabled,
            allowed_hosts=settings.tools.allowed_hosts,
        )
        self._agent_settings = settings.agent
        self._tool_timeout_s = settings.tools.execution_timeout_s
        self._max_retries = settings.tools.max_retries
        self._retry_backoff_s = settings.tools.retry_backoff_s

        if http_client is not None:
            self._client = http_client
        else:
            client_kwargs: dict[str, Any] = {
                "timeout": httpx.Timeout(self._tool_timeout_s),
                "limits": httpx.Limits(max_keepalive_connections=20, max_connections=100),
            }
            if settings.tools.http2_enabled:
                try:
                    import h2  # noqa: F401, PLC0415

                    client_kwargs["http2"] = True
                except ImportError:
                    logger.warning("http2_disabled", reason="h2 package not installed")
            if settings.tools.proxy_url:
                client_kwargs["proxies"] = settings.tools.proxy_url
            self._client = httpx.AsyncClient(**client_kwargs)

    async def execute(  # noqa: PLR0912, PLR0915
        self,
        tool: ToolRead,
        inputs: dict[str, Any],
        context: ExecutionContext,
        session: AsyncSession,
        skip_approval: bool = False,
    ) -> ToolResult:
        """Execute a tool and return the result.

        The full pipeline:
        1. Approval gate check (raises ``ApprovalRequiredInterrupt`` if needed)
        2. Input validation against ``tool.input_schema``
        3. Sandbox host whitelist check
        4. Auth header resolution
        5. HTTP call with retry policy
        6. Output validation against ``tool.output_schema``
        7. Persist ``ToolExecution`` row
        8. Publish tool event to Redis

        Args:
            tool: The tool definition to execute.
            inputs: The input parameters for the tool call.
            context: Execution context (tenant, user, session).
            session: Database session for persisting the execution record.

        Returns:
            A ``ToolResult`` summarising the execution outcome.
        """
        # 1. Approval gate (skip if pre-approved by the graph node)
        if not skip_approval:
            check = check_approval_required(
                tool,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                session_id=context.session_id,
                agent_run_id=context.agent_run_id,
                settings=self._agent_settings,
            )
            if check.required:
                raise ApprovalRequiredInterrupt(
                    tool_name=tool.name,
                    inputs=inputs,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    session_id=context.session_id,
                    agent_run_id=context.agent_run_id,
                )

        # 2. Input validation
        if tool.input_schema:
            try:
                jsonschema.validate(inputs, tool.input_schema)
            except jsonschema.ValidationError as exc:
                logger.warning("tool.input_validation_failed", tool=tool.name, error=str(exc))
                return ToolResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    status="validation_error",
                    error=f"Input validation failed: {exc.message}",
                    duration_ms=0,
                )

        # 3. Sandbox
        try:
            check_allowed_host(tool.endpoint_url, self._sandbox_config.allowed_hosts)
        except SandboxBlockedError as exc:
            logger.warning("tool.sandbox_blocked", tool=tool.name, host=exc.host)
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="error",
                error=str(exc),
                duration_ms=0,
            )

        # 4. Auth resolution
        headers = await self._resolve_auth(tool)
        masked_log_headers = mask_sensitive_fields(dict(headers))

        # 5. Body size limit
        if self._sandbox_config.enabled:
            body_bytes = len(json.dumps(inputs).encode("utf-8"))
            if body_bytes > self._sandbox_config.max_request_bytes:
                logger.warning(
                    "tool.body_too_large",
                    tool=tool.name,
                    size=body_bytes,
                    limit=self._sandbox_config.max_request_bytes,
                )
                return ToolResult(
                    tool_id=tool.id,
                    tool_name=tool.name,
                    status="validation_error",
                    error=(
                        f"Request body exceeds max size "
                        f"({body_bytes} > {self._sandbox_config.max_request_bytes})"
                    ),
                    duration_ms=0,
                )

        start = time.perf_counter()
        retried = False
        last_exc: Exception | None = None
        response: httpx.Response | None = None

        # 6. Rate limit check (Redis token bucket per tool)
        if tool.rate_limit_per_minute is not None and tool.rate_limit_per_minute > 0:
            redis = get_redis_client()
            if redis is not None:
                rl_key = f"tool:rl:{tool.id}"
                limiter = TokenBucketRateLimiter(
                    redis,
                    rate=tool.rate_limit_per_minute / 60.0,
                    capacity=float(tool.rate_limit_per_minute),
                )
                try:
                    await limiter.acquire(rl_key, raise_on_limit=True)
                except RateLimitError as exc:
                    logger.warning("tool.rate_limited", tool=tool.name, key=rl_key)
                    return ToolResult(
                        tool_id=tool.id,
                        tool_name=tool.name,
                        status="rate_limited",
                        error=str(exc),
                        duration_ms=0,
                    )

        # 7. HTTP call with retry
        retry_policy = http_retry_policy(
            max_attempts=self._max_retries,
            backoff_base_s=self._retry_backoff_s,
        )

        HTTP_429_TOO_MANY: int = 429
        total_attempts = 0

        try:
            async for attempt in retry_policy:
                total_attempts += 1
                with attempt:
                    try:
                        response = await self._execute_http(
                            tool,
                            inputs,
                            headers,
                            retry_count=attempt.retry_state.attempt_number - 1,
                        )
                    except httpx.HTTPStatusError as exc:
                        response = exc.response
                        if not is_retryable_status(response.status_code):
                            last_exc = exc
                            raise
                        if response.status_code == HTTP_429_TOO_MANY:
                            retry_after = parse_retry_after(response)
                            if retry_after is not None:
                                await asyncio.sleep(retry_after)
                        raise
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        last_exc = exc
                        raise
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError):
            # All retries exhausted or non-retryable — response/last_exc already set
            pass

        retried = total_attempts > 1
        duration_ms = int((time.perf_counter() - start) * 1000)

        # Build result
        result = self._build_result(tool, response, last_exc, duration_ms, retried)

        # 7. Output validation (soft-fail)
        if result.data is not None and tool.output_schema:
            try:
                jsonschema.validate(result.data, tool.output_schema)
            except jsonschema.ValidationError as exc:
                logger.info("tool.output_validation_failed", tool=tool.name, error=str(exc))
                result.status = "validation_error"
                result.error = (result.error or "") + f"; Output validation: {exc.message}"

        # 8. Persist (gracefully handle DB errors so tool result is still returned)
        try:
            await self._persist_execution(session, tool, context, result, inputs)
        except Exception as persist_exc:
            logger.warning("tool.persist_failed", tool=tool.name, error=str(persist_exc))

        # 9. Publish event
        await self._publish_event(context, result)

        logger.info(
            "tool.executed",
            tool=tool.name,
            status=result.status,
            http_status=result.http_status,
            duration_ms=result.duration_ms,
            headers=masked_log_headers,
        )
        return result

    async def _resolve_auth(self, tool: ToolRead) -> dict[str, str]:
        """Build auth headers for the tool call."""
        if tool.auth_type == "none" or not tool.auth_type:
            return {}

        header_name = AUTH_HEADERS.get(tool.auth_type)
        if header_name is None:
            logger.warning("tool.unknown_auth_type", tool=tool.name, auth_type=tool.auth_type)
            return {}

        resolved = self._secret_resolver.resolve(tool.auth_ref or tool.auth_type)
        secret_value = resolved.get_secret_value()
        if not secret_value:
            logger.warning("tool.auth_ref_empty", tool=tool.name, auth_type=tool.auth_type)
            return {}

        if tool.auth_type == "api_key":
            return {header_name: secret_value}

        return {"Authorization": f"{header_name} {secret_value}"}

    async def _execute_http(
        self,
        tool: ToolRead,
        inputs: dict[str, Any],
        headers: dict[str, str],
        retry_count: int = 0,
    ) -> httpx.Response:
        """Perform a single HTTP call to the tool endpoint."""
        method = tool.http_method.lower()

        if method == "get":
            resp = await self._client.get(tool.endpoint_url, params=inputs, headers=headers)
        else:
            resp = await self._client.request(
                method, tool.endpoint_url, json=inputs, headers=headers
            )

        resp.raise_for_status()
        return resp

    def _build_result(
        self,
        tool: ToolRead,
        response: httpx.Response | None,
        error: Exception | None,
        duration_ms: int,
        retried: bool,
    ) -> ToolResult:
        """Construct a ``ToolResult`` from the HTTP response or error."""
        if response is not None:
            raw = response.text
            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError):
                data = None

            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="success" if response.is_success else "error",
                http_status=response.status_code,
                data=data,
                duration_ms=duration_ms,
                retried=retried,
                raw_response_excerpt=raw,
                response_headers=dict(response.headers),
            )

        if isinstance(error, httpx.TimeoutException):
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="timeout",
                error=str(error),
                duration_ms=duration_ms,
                retried=retried,
            )

        return ToolResult(
            tool_id=tool.id,
            tool_name=tool.name,
            status="error",
            error=str(error) if error else "Unknown error",
            duration_ms=duration_ms,
            retried=retried,
        )

    @staticmethod
    async def _persist_execution(
        session: AsyncSession,
        tool: ToolRead,
        context: ExecutionContext,
        result: ToolResult,
        inputs: dict[str, Any],
    ) -> None:
        """Write a ``ToolExecution`` row to the database."""
        execution = ToolExecution(
            tenant_id=context.tenant_id,
            tool_id=tool.id,
            session_id=context.session_id,
            agent_run_id=context.agent_run_id,
            request_payload=inputs,
            response_payload=result.data,
            status=result.status,
            http_status=result.http_status,
            duration_ms=result.duration_ms,
            error_message=result.error,
            retried=result.retried,
        )
        session.add(execution)
        await session.flush()

    async def _publish_event(self, context: ExecutionContext, result: ToolResult) -> None:
        """Publish a tool execution event to Redis."""
        if self._event_bus is None:
            return

        event = {
            "type": "tool_execution",
            "tool_id": str(result.tool_id),
            "tool_name": result.tool_name,
            "status": result.status,
            "http_status": result.http_status,
            "duration_ms": result.duration_ms,
            "retried": result.retried,
        }
        await self._event_bus.publish(tool_channel(context.session_id), event)

    async def close(self) -> None:
        """Close the underlying ``httpx.AsyncClient``."""
        await self._client.aclose()
