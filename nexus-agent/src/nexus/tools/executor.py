"""ToolExecutor — performs outbound HTTP API calls or MCP server requests.

The executor is the only component that touches external APIs. It enforces
auth injection, input/output schema validation, retries, sandbox, approval
gating, and persistence. Does NOT support Python code execution.
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
from nexus.observability.tracing import get_tracer
from nexus.db.models.tool import ToolExecution
from nexus.redis_client.client import get_redis_client
from nexus.redis_client.pubsub import EventBus, tool_channel
from nexus.redis_client.rate_limiter import RateLimitError, TokenBucketRateLimiter
from nexus.tools.mcp_client import MCPClient
from nexus.tools.result import ToolResult
from nexus.tools.retries import category_retry_delay, http_retry_policy, is_retryable_status, parse_retry_after
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

_PYTHON_CODE_KEYWORDS: frozenset[str] = frozenset(
    {
        "code", "script", "python", "exec", "eval", "compile",
        "subprocess", "__import__", "importlib", "run_python",
        "exec_python", "sandbox_code",
    }
)


def _check_python_code_fields(tool: ToolRead) -> str | None:
    """Return an error message if the tool contains Python code fields."""
    schemas_to_check = {
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "validation_rules": tool.validation_rules,
    }
    for field_name, schema in schemas_to_check.items():
        if schema and isinstance(schema, dict):
            for key in schema:
                if key.lower() in _PYTHON_CODE_KEYWORDS:
                    return (
                        f"Tool '{tool.name}' contains Python code reference "
                        f"'{key}' in {field_name} — rejected"
                    )
            # Recurse into nested properties
            props = schema.get("properties", {})
            if isinstance(props, dict):
                for prop_key in props:
                    if prop_key.lower() in _PYTHON_CODE_KEYWORDS:
                        return (
                            f"Tool '{tool.name}' contains Python code reference "
                            f"'{prop_key}' in {field_name}.properties — rejected"
                        )
    return None


_COMMON_FIELD_MAP: dict[str, str] = {
    "q": "query", "query": "q",
    "name": "title", "title": "name",
    "id": "identifier", "identifier": "id",
    "email": "email_address", "email_address": "email",
    "lat": "latitude", "latitude": "lat",
    "lon": "longitude", "longitude": "lon", "long": "lon",
    "city": "location", "location": "city",
}


def _semantic_fix_inputs(inputs: dict[str, Any], error_fields: list[str]) -> dict[str, Any]:
    """Attempt to fix input parameters based on field names in error messages."""
    fixed = dict(inputs)
    for field in error_fields:
        lower = field.lower()
        if lower in _COMMON_FIELD_MAP and _COMMON_FIELD_MAP[lower] in fixed:
            fixed[field] = fixed.pop(_COMMON_FIELD_MAP[lower])
    return fixed


class ExecutionContext:
    """Context for a single tool execution."""

    def __init__(
        self,
        session_id: uuid.UUID,
        agent_run_id: uuid.UUID | None = None,
    ) -> None:
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
        self._mcp_client = MCPClient()
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

    async def execute(  # noqa: PLR0911, PLR0912, PLR0915
        self,
        tool: ToolRead,
        inputs: dict[str, Any],
        context: ExecutionContext,
        session: AsyncSession,
        skip_approval: bool = False,
    ) -> ToolResult:
        """Execute an HTTP API call or MCP server request — no code execution.

        The full pipeline:
        1. Input validation against ``tool.input_schema``
        3. Python code injection check (rejects tools with code fields)
        4. Sandbox host whitelist check (HTTP tools only)
        5. Auth header resolution
        6. Body size limit check
        7. Rate limit check (Redis token bucket)
        8. HTTP call with retry (``http_api``) or MCP ``tools/call`` (``mcp``)
        9. Output validation against ``tool.output_schema``
       10. Persist ``ToolExecution`` row
       11. Publish tool event to Redis

        Args:
            tool: The tool definition to execute.
            inputs: The input parameters for the tool call.
            context: Execution context (tenant, user, session).
            session: Database session for persisting the execution record.

        Returns:
            A ``ToolResult`` summarising the execution outcome.
        """
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

        # 3. Python code injection check
        code_err = _check_python_code_fields(tool)
        if code_err:
            logger.warning("tool.code_rejected", tool=tool.name, reason=code_err)
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="validation_error",
                error=code_err,
                duration_ms=0,
            )

        # 4. Route by tool_type
        if tool.tool_type == "mcp":
            return await self._execute_mcp(tool, inputs, context, session)

        # 5. Sandbox (HTTP only)
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

        # 6. Auth resolution
        headers = await self._resolve_auth(tool)
        masked_log_headers = mask_sensitive_fields(dict(headers))

        # 7. Body size limit
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

        # 8. Rate limit check (Redis token bucket per tool)
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

        # 9. HTTP call with retry (semantic-aware)
        retry_policy = http_retry_policy(
            max_attempts=self._max_retries,
            backoff_base_s=self._retry_backoff_s,
        )

        HTTP_429_TOO_MANY: int = 429
        total_attempts = 0
        _sem_classifier = None

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
                        # Semantic-aware delay and param modification
                        if _sem_classifier is None:
                            from nexus.tools.error_recovery import SemanticErrorClassifier  # noqa: PLC0415
                            _sem_classifier = SemanticErrorClassifier()
                        err_text = str(exc)
                        category = _sem_classifier.classify(err_text)

                        if response.status_code == HTTP_429_TOO_MANY:
                            retry_after = parse_retry_after(response)
                            delay = category_retry_delay(category.value, attempt.retry_state.attempt_number - 1, retry_after)
                            if delay > 0:
                                await asyncio.sleep(delay)
                        else:
                            delay = category_retry_delay(category.value, attempt.retry_state.attempt_number - 1)
                            if delay > 0:
                                await asyncio.sleep(delay)

                        # For schema errors, try to fix inputs and retry
                        if category.name == "PERMANENT_SCHEMA":
                            fields = _sem_classifier.extract_fields(err_text)
                            if fields:
                                fixed = _semantic_fix_inputs(inputs, fields)
                                if fixed != inputs:
                                    logger.info("tool.schema_retry_fix", tool=tool.name, fields=fields)
                                    inputs = fixed
                        raise
                    except (httpx.TimeoutException, httpx.TransportError) as exc:
                        last_exc = exc
                        raise
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError):
            pass

        retried = total_attempts > 1
        duration_ms = int((time.perf_counter() - start) * 1000)

        # Tracing span for this tool execution
        _span_tool = get_tracer().start_span("tool.execute")
        _span_tool.set_attribute("tool.name", tool.name)
        _span_tool.set_attribute("tool.type", tool.tool_type)

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

        # Record performance metrics (fire-and-forget, non-blocking)
        try:
            from nexus.tools.performance import performance_tracker  # noqa: PLC0415
            performance_tracker.record_call(
                tool_id=tool.name,
                latency_ms=result.duration_ms or 0,
                success=result.status == "success",
                error_type=result.status if result.status != "success" else None,
            )
        except Exception:
            pass

        logger.info(
            "tool.executed",
            tool=tool.name,
            status=result.status,
            http_status=result.http_status,
            duration_ms=result.duration_ms,
            headers=masked_log_headers,
        )

        _span_tool.set_attribute("tool.status", result.status)
        _span_tool.set_attribute("tool.duration_ms", result.duration_ms or 0)
        _span_tool.end()
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

    async def _execute_mcp(
        self,
        tool: ToolRead,
        inputs: dict[str, Any],
        context: ExecutionContext,
        session: AsyncSession,
    ) -> ToolResult:
        """Execute a tool via an external MCP server — no code execution."""
        result = await self._mcp_client.call_mcp_tool(
            server_url=tool.mcp_server_url,
            tool_name=tool.name,
            arguments=inputs,
        )

        # Output validation (soft-fail)
        if result.data is not None and tool.output_schema:
            try:
                jsonschema.validate(result.data, tool.output_schema)
            except jsonschema.ValidationError as exc:
                logger.info("tool.output_validation_failed", tool=tool.name, error=str(exc))
                result.status = "validation_error"
                result.error = (result.error or "") + f"; Output validation: {exc.message}"

        # Persist
        try:
            await self._persist_execution(session, tool, context, result, inputs)
        except Exception as persist_exc:
            logger.warning("tool.persist_failed", tool=tool.name, error=str(persist_exc))

        # Publish event
        await self._publish_event(context, result)

        logger.info(
            "tool.mcp_executed",
            tool=tool.name,
            status=result.status,
            duration_ms=result.duration_ms,
        )
        return result

    async def _execute_http(
        self,
        tool: ToolRead,
        inputs: dict[str, Any],
        headers: dict[str, str],
        retry_count: int = 0,
    ) -> httpx.Response:
        """Perform a single outbound HTTP API call via httpx — no code execution."""
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
