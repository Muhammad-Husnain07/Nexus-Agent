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
from nexus.db.models.tool import ToolExecution
from nexus.observability.tracing import get_tracer
from nexus.redis_client.client import get_redis_client

# FK-REPAIR (P2-E): the synthetic stub identity used when a tool has no
# registry row. NOT a registry identity — never valid as tool_execution.tool_id.
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
from nexus.redis_client.pubsub import EventBus, tool_channel
from nexus.redis_client.rate_limiter import RateLimitError, TokenBucketRateLimiter
from nexus.tools.mcp_client import MCPClient
from nexus.tools.result import ToolResult
from nexus.tools.retries import (
    category_retry_delay,
    http_retry_policy,
    is_retryable_status,
    parse_retry_after,
)
from nexus.tools.sandbox import (
    SandboxBlockedError,
    SandboxConfig,
    check_allowed_host,
    mask_sensitive_fields,
)
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.tools.executor")


def _get_settings_tools() -> Any:
    """Return tools settings, or a fallback default if settings fail."""
    try:
        return get_settings().tools
    except Exception:
        from nexus.config.settings import ToolSettings
        return ToolSettings()


def _check_python_code_fields(tool: ToolRead) -> str | None:
    """Return an error message if the tool contains Python code fields."""
    settings = _get_settings_tools()
    keywords = frozenset(settings.python_code_keywords)
    schemas_to_check = {
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "validation_rules": tool.validation_rules,
    }
    for field_name, schema in schemas_to_check.items():
        if schema and isinstance(schema, dict):
            for key in schema:
                if key.lower() in keywords:
                    return (
                        f"Tool '{tool.name}' contains Python code reference "
                        f"'{key}' in {field_name} — rejected"
                    )
            # Recurse into nested properties
            props = schema.get("properties", {})
            if isinstance(props, dict):
                for prop_key in props:
                    if prop_key.lower() in keywords:
                        return (
                            f"Tool '{tool.name}' contains Python code reference "
                            f"'{prop_key}' in {field_name}.properties — rejected"
                        )
    return None


def _semantic_fix_inputs(inputs: dict[str, Any], error_fields: list[str]) -> dict[str, Any]:
    """Attempt to fix input parameters based on field names in error messages."""
    settings = _get_settings_tools()
    field_map = settings.common_field_map
    fixed = dict(inputs)
    for field in error_fields:
        lower = field.lower()
        if lower in field_map and field_map[lower] in fixed:
            fixed[field] = fixed.pop(field_map[lower])
    return fixed


def _effective_max_attempts(idempotent: bool, max_retries: int) -> int:
    """Number of HTTP attempts for a tool, driven by its idempotency flag.

    A non-idempotent tool must never be retried automatically — the first
    attempt may have fired a side effect (e.g. a payment or a write) that a
    retry would duplicate and cannot be undone. Idempotent tools retry
    safely. Metadata-driven: the flag comes from the tool definition.
    """
    return (max_retries + 1) if idempotent else 1


def _output_validation_error(data: Any, schema: Any) -> str | None:
    """Validate tool output against its declared schema.

    The executor wraps top-level array responses as ``{"results": [...]}``
    for downstream artifact handling — when the schema declares a top-level
    array, the wrapped list is unwrapped back before validation (metadata-
    driven: follows the schema's declared type, no assumptions).

    Returns the validation error message, or ``None`` when valid.
    """
    if not isinstance(schema, dict):
        return None
    candidate = data
    if (
        isinstance(candidate, dict)
        and isinstance(candidate.get("results"), list)
        and schema.get("type") == "array"
    ):
        candidate = candidate["results"]
    try:
        jsonschema.validate(candidate, schema)
        return None
    except jsonschema.ValidationError as exc:
        return str(exc.message)


def _apply_schema_defaults(
    inputs: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing inputs from their JSON Schema ``default`` values.

    The planner only emits the parameters it extracted from the query; a
    tool contract may declare optional parameters with defaults (e.g.
    ``current_weather`` with ``default: true``). Without filling them, an
    unfilled URL template placeholder (``&current_weather={current_weather}``)
    is sent literally and the API rejects the request. Metadata-driven: no
    hardcoded parameter names.
    """
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return inputs
    filled: dict[str, Any] = dict(inputs)
    for name, prop in props.items():
        if not isinstance(prop, dict):
            continue
        if name not in filled and "default" in prop and prop.get("default") is not None:
            filled[name] = prop["default"]
    return filled


def _coerce_value_to_type(declared: str, value: Any) -> tuple[Any, bool]:
    """Coerce a single input value to its declared JSON Schema type.

    Fully metadata-driven (no hardcoded names): a declared ``string``
    receiving a scalar is stringified; a declared ``number``/``integer``
    receiving a numeric string is parsed back; integral floats map to
    integers.

    Returns ``(value, changed)`` — ``changed`` is False when no conversion
    applied.
    """
    scalar_bool_int_float = (bool, int, float)
    if (
        declared == "string"
        and isinstance(value, scalar_bool_int_float)
        and not isinstance(value, str)
    ):
        return ("true" if value else "false") if isinstance(value, bool) else str(value), True
    if declared in ("number", "integer") and isinstance(value, str) and value.strip():
        try:
            return (int(value) if declared == "integer" else float(value)), True
        except (ValueError, TypeError):
            return value, False
    # A schema-declared ``boolean`` receiving a boolean-like string
    # ("true"/"false"/"1"/"0" from planner extraction) is parsed back —
    # metadata-driven, same rule as numeric strings.
    if declared == "boolean" and isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True, True
        if low in ("false", "0", "no"):
            return False, True
        return value, False
    if declared == "number" and isinstance(value, int) and not isinstance(value, bool):
        return float(value), True
    if declared == "integer" and isinstance(value, float) and value.is_integer():
        return int(value), True
    return value, False


def _coerce_declared_values(coerced: dict[str, Any], props: dict[str, Any]) -> bool:
    """Apply type coercion to each provided input (returns changed flag)."""
    changed = False
    for name, prop in props.items():
        if not isinstance(prop, dict) or name not in coerced:
            continue
        new_value, value_changed = _coerce_value_to_type(prop.get("type"), coerced[name])
        if value_changed:
            coerced[name] = new_value
            changed = True
    return changed


def _coerce_inputs_to_schema(
    inputs: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any] | None:
    """Coerce/remap input values to match the JSON Schema declared types.

    Two metadata-driven fixes (no hardcoded field names):
    1. **Key remap** — an input key the schema doesn't declare is remapped:
       first via the schema's explicit ``x-aliases`` extension (O(1)), then
       via the shared RapidFuzz core at the configured threshold. The LLM
       often invents param names (e.g. ``pokemon`` instead of
       ``pokemon_name``).
    2. **Scalar coercion** — a property declared as ``string`` receiving a
       scalar (bool/int/float) is stringified.
    3. **Numeric coercion** — a property declared as ``number``/``integer``
       receiving a numeric string (e.g. ``"74.3587"`` from extraction) is
       parsed back to the declared type.

    Returns a new dict, or ``None`` when no change was possible/applicable.
    """
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return None
    changed = False
    coerced: dict[str, Any] = dict(inputs)

    # 1. Remap unknown keys onto declared properties.
    declared_props: dict[str, str] = {
        str(p): str(p) for p in props if isinstance(p, str)
    }
    # Explicit schema-declared aliases (x-aliases extension) — O(1).
    alias_map: dict[str, str] = {}
    for prop_name, prop in props.items():
        if not isinstance(prop, dict):
            continue
        for alias in (prop.get("x-aliases") or []):
            if isinstance(alias, str) and alias.strip():
                alias_map[alias.strip().lower()] = str(prop_name)

    for key in list(coerced.keys()):
        if key in declared_props:
            continue
        # 1a. Declared alias first (exact, strong signal).
        match = alias_map.get(key.lower())
        # 1b. Fuzzy fallback via the shared RapidFuzz core (≥ threshold).
        if match is None:
            from nexus.capabilities.resolution import fuzzy_best_match

            best = fuzzy_best_match(key, list(declared_props.keys()))
            if best is not None:
                match = best[0]
        if match is not None and match in declared_props and match != key:
            coerced[match] = coerced.pop(key)
            changed = True

    # 2. Coerce values to their declared types (stringify, numeric parse).
    if _coerce_declared_values(coerced, props):
        changed = True
    return coerced if changed else None


class ExecutionContext:
    """Context for a single tool execution.

    P2-C: ``agent_run_id`` (the parent invocation) and ``execution_key``
    (the logical operation identity — stable across retries) are persisted
    with the ToolExecution row, so every attempt joins back to its parent
    request and run without log parsing. ``idempotency_key`` is set
    dynamically by the executor (the provider-facing key derived from the
    execution key).
    """

    def __init__(
        self,
        session_id: uuid.UUID,
        agent_run_id: uuid.UUID | None = None,
        execution_key: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.agent_run_id = agent_run_id
        self.execution_key = execution_key


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
        self._settings = get_settings()
        settings = self._settings
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
                "follow_redirects": True,
                "headers": {
                    "User-Agent": settings.tools.user_agent,
                    "Accept": "application/json",
                },
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
            # 2a. Fill schema-declared defaults for parameters the planner
            # omitted (metadata-driven — no hardcoded names).
            filled_inputs = _apply_schema_defaults(inputs, tool.input_schema)
            if filled_inputs != inputs:
                logger.info(
                    "tool.defaults_applied",
                    tool=tool.name,
                    added=[k for k in filled_inputs if k not in inputs],
                )
                inputs = filled_inputs
            try:
                jsonschema.validate(inputs, tool.input_schema)
            except jsonschema.ValidationError as exc:
                # Schema-driven coercion attempt: when a property is declared
                # as a string but the planner produced a scalar (bool/int/float,
                # e.g. "set maintenance_mode to true" → value=True), coerce the
                # scalar to its string form and re-validate. Fully metadata-
                # driven — no hardcoded property names.
                coerced = _coerce_inputs_to_schema(inputs, tool.input_schema)
                if coerced is not None:
                    try:
                        jsonschema.validate(coerced, tool.input_schema)
                    except jsonschema.ValidationError:
                        coerced = None
                if coerced is None:
                    logger.warning("tool.input_validation_failed", tool=tool.name, error=str(exc))
                    return ToolResult(
                        tool_id=tool.id,
                        tool_name=tool.name,
                        status="validation_error",
                        error=f"Input validation failed: {exc.message}",
                        duration_ms=0,
                    )
                inputs = coerced

        # 2.5 Circuit breaker — reject early when the provider is tripping.
        from nexus.tools.circuit_breaker import is_open

        if is_open(tool.name):
            logger.warning(
                "tool.circuit_open",
                tool=tool.name,
                hint="Provider temporarily disabled after repeated failures",
            )
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="unavailable",
                error=f"Provider '{tool.name}' is temporarily disabled (circuit open)",
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

        # 5. Sandbox (HTTP only) — the whitelist check always runs on the
        # registered endpoint. SSRF hardening (strict mode) applies when the
        # URL host was influenced by tool inputs (the dynamic-endpoint
        # class): the executor's own URL-template resolution is compared
        # against the operator-registered host.
        try:
            _registered_host = tool.endpoint_url.split("/")[2] if "//" in tool.endpoint_url else tool.endpoint_url
            _dynamic = bool(
                inputs and any(
                    isinstance(v, str) and "://" in v
                    for v in (inputs.values() if isinstance(inputs, dict) else [inputs])
                )
            )
            check_allowed_host(
                tool.endpoint_url,
                self._sandbox_config.allowed_hosts,
                enforce_ssrf=_dynamic,
            )
        except SandboxBlockedError as exc:
            logger.warning("tool.sandbox_blocked", tool=tool.name, host=exc.host)
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="error",
                error=str(exc),
                duration_ms=0,
            )

        # 5b. AUTHORIZATION GATE (P0): a capability whose execution policy
        # (``validation_rules.allowed_roles`` — the operator-configured
        # contract carrier) declares roles is executable ONLY by callers
        # whose roles intersect the declared set. Unconfigured capabilities
        # remain open — the operator's explicit choice.
        try:
            _meta = tool.validation_rules if isinstance(
                getattr(tool, "validation_rules", None), dict
            ) else {}
            _allowed_roles = _meta.get("allowed_roles")
            _caller_roles = list(getattr(context, "user_roles", None) or [])
            if _allowed_roles:
                _allowed = {str(r) for r in _allowed_roles}
                if not (_allowed & set(_caller_roles)):
                    logger.warning(
                        "tool.authorization_denied",
                        tool=tool.name,
                        allowed=sorted(_allowed),
                        caller=sorted(_caller_roles),
                    )
                    return ToolResult(
                        tool_id=tool.id,
                        tool_name=tool.name,
                        status="error",
                        error=(
                            f"authorization denied: capability '{tool.name}' "
                            f"requires roles {sorted(_allowed)}"
                        ),
                        duration_ms=0,
                    )
        except Exception:
            pass  # the authorization gate is metadata-driven; never breaks the call

        # 6. Auth resolution — ensure User-Agent is always sent
        headers = await self._resolve_auth(tool)
        if "User-Agent" not in headers:
            headers["User-Agent"] = self._settings.tools.user_agent
        # IDEMPOTENCY (P0): when the tool declares a provider-facing
        # idempotency header (``validation_rules.idempotency_header``,
        # operator-configured) and the invocation carries the stable
        # idempotency key, stamp it on the request — a retried/recovered
        # call carries the SAME key, so the provider can deduplicate side
        # effects.
        try:
            _meta = tool.validation_rules if isinstance(
                getattr(tool, "validation_rules", None), dict
            ) else {}
            _idem_header = _meta.get("idempotency_header")
            _idem_key = getattr(context, "idempotency_key", None)
            if _idem_header and _idem_key and _idem_header not in headers:
                headers[_idem_header] = _idem_key
        except Exception:
            pass  # idempotency stamping is best-effort; never breaks the call
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
        # max_attempts = initial call + retries. The retry budget comes from
        # the capability's declarative execution policy (metadata-driven);
        # non-idempotent tools are NEVER retried — a retried call may
        # duplicate an already-fired side effect.
        try:
            from nexus.execution.policy import policy_for_capability

            _policy = policy_for_capability(tool.name)
            _retries = int(_policy.retries)
            _timeout_s = float(_policy.timeout_s)
        except Exception:
            _retries = self._max_retries
            _timeout_s = float(self._tool_timeout_s)
        retry_policy = http_retry_policy(
            max_attempts=_effective_max_attempts(tool.idempotent, _retries),
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
                            from nexus.tools.error_recovery import (
                                SemanticErrorClassifier,  # noqa: PLC0415
                            )
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
                    except SandboxBlockedError as exc:
                        # Final-URL sandbox block (C1/P0-C): never retried,
                        # surfaced as an explicit tool error.
                        last_exc = exc
                        raise
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError, SandboxBlockedError):
            pass

        retried = total_attempts > 1
        duration_ms = int((time.perf_counter() - start) * 1000)

        # Tracing span for this tool execution
        _span_tool = get_tracer().start_span("tool.execute")
        _span_tool.set_attribute("tool.name", tool.name)
        _span_tool.set_attribute("tool.type", tool.tool_type)

        # Build result
        result = self._build_result(tool, response, last_exc, duration_ms, retried)

        # Circuit breaker outcome recording — success closes / failure trips
        from nexus.tools.circuit_breaker import record_failure, record_success

        if result.status == "success":
            record_success(tool.name)
        elif result.status in ("error", "timeout"):
            record_failure(tool.name)

        # 7. Output validation (soft-fail) — NEVER validate error bodies; a
        # failed HTTP call already has status="error" and its payload is
        # diagnostic only.
        if result.status == "success" and result.data is not None and tool.output_schema:
            if not isinstance(result.data, dict):
                logger.warning(
                    "tool.output_not_dict",
                    tool=tool.name,
                    data_type=type(result.data).__name__,
                    data_preview=str(result.data)[:200],
                )
            else:
                output_error = _output_validation_error(result.data, tool.output_schema)
                if output_error:
                    logger.info("tool.output_validation_failed", tool=tool.name, error=output_error)
                    result.status = "validation_error"
                    result.error = (result.error or "") + f"; Output validation: {output_error}"

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
        """Build auth headers for the tool call.

        C4/P0-C: an explicit ``auth_ref`` (an env-var reference injected
        into the request) is resolved ONLY when the ref is on the
        operator-configured allowlist — arbitrary env-var references are
        denied, closing the server-side secret-exfiltration channel.
        """
        if tool.auth_type == "none" or not tool.auth_type:
            return {}

        auth_map = self._settings.tools.auth_header_mappings
        header_name = auth_map.get(tool.auth_type)
        if header_name is None:
            logger.warning("tool.unknown_auth_type", tool=tool.name, auth_type=tool.auth_type)
            return {}

        _ref = tool.auth_ref or tool.auth_type
        if tool.auth_ref:
            allowlist = list(
                getattr(self._settings.tools, "auth_ref_allowlist", None) or []
            )
            if _ref not in allowlist:
                logger.warning(
                    "tool.auth_ref_not_allowlisted",
                    tool=tool.name,
                    ref=_ref,
                )
                return {}

        resolved = self._secret_resolver.resolve(_ref)
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
        # SANDBOX CHECK (C1/P0-C): the MCP server destination is validated
        # like the dynamic-endpoint class — an MCP server_url pointing at
        # an internal/metadata address must never be connected to.
        try:
            check_allowed_host(
                tool.mcp_server_url or "",
                self._sandbox_config.allowed_hosts,
                enforce_ssrf=True,
            )
        except SandboxBlockedError as exc:
            logger.warning("tool.sandbox_blocked", tool=tool.name, host=exc.host)
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="error",
                error=str(exc),
                duration_ms=0,
            )

        result = await self._mcp_client.call_mcp_tool(
            server_url=tool.mcp_server_url,
            tool_name=tool.name,
            arguments=inputs,
            idempotent=bool(getattr(tool, "idempotent", False)),
        )

        # Output validation (soft-fail)
        if result.data is not None and tool.output_schema:
            output_error = _output_validation_error(result.data, tool.output_schema)
            if output_error:
                logger.info("tool.output_validation_failed", tool=tool.name, error=output_error)
                result.status = "validation_error"
                result.error = (result.error or "") + f"; Output validation: {output_error}"

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
        url = tool.endpoint_url
        url_params: dict[str, Any] = dict(inputs)

        # Resolve URL template placeholders — e.g. {id} → inputs["id"]
        if "{" in url:
            import re as _re
            resolved = url
            for match in _re.finditer(r"\{(\w+)\}", url):
                param = match.group(1)
                if param in inputs:
                    raw = inputs[param]
                    if isinstance(raw, bool):
                        raw = "true" if raw else "false"
                    if isinstance(raw, str):
                        # A value that cannot be a real path segment —
                        # empty, a null-sentinel string (``"None"`` from
                        # an unresolved placeholder/serialization), or a
                        # literal unresolved ``${...}`` — is treated as
                        # absent: optional segments are stripped below,
                        # required ones raise (never ``/posts/None``).
                        if (not raw.strip() or raw.strip().lower() == "none"
                                or raw.startswith("${")):
                            raw = None
                    if raw is not None:
                        resolved = resolved.replace(match.group(0), str(raw))
                        url_params.pop(param, None)
                    else:
                        # Absent value (null sentinel / unresolved
                        # placeholder): it must not leak into the query
                        # string either — drop it entirely.
                        url_params.pop(param, None)
            url = resolved

            # Unfilled placeholders must never be sent literally. REQUIRED
            # path segments (schema ``required`` — metadata-driven) are a
            # permanent error — the request cannot be formed. Optional
            # segments are stripped: a TRAILING one (``/posts/{id}`` with
            # ``id`` omitted → ``/posts``) is removed; a MIDDLE one cannot
            # be safely removed, so it errors explicitly.
            _path, _sep, _query = url.partition("?")
            _required_params = set(
                (tool.input_schema or {}).get("required") or []
            ) if isinstance(tool.input_schema, dict) else set()
            remaining = list(_re.finditer(r"\{(\w+)\}", url))
            for m in remaining:
                param = m.group(1)
                in_path = m.start() < (len(_path) if _sep else len(url))
                if not in_path:
                    continue
                trailing = url[m.end():] == "" or url[m.end():] == "/"
                if param in _required_params or not trailing:
                    raise ValueError(
                        f"Missing required path parameter(s) for '{tool.name}': {param} "
                        f"(not provided in inputs {sorted(inputs)})"
                    )
                # Optional trailing segment → strip "/{param}"
                url = url[: m.start()].rstrip("/")
            if _sep:
                for m in _re.finditer(r"[?&]\{(\w+)\}", _query):
                    url = url.replace(m.group(0), "")
                url = url.rstrip("?&")

        # Extra (non-placeholder) params are MERGED into the URL query string
        # directly. Never passed via httpx's ``params=`` kwarg: httpx REPLACES
        # a URL's existing query string when params= is given, which would
        # wipe the resolved endpoint parameters (the historical
        # ``get_current_weather`` empty-body bug). Merging keeps everything on
        # the wire with no wipe — stray context keys (e.g. the workflow
        # layer's ``place``) are harmless because the real parameters stay.
        if url_params:
            try:
                from urllib.parse import urlencode

                encoded = urlencode(
                    [(str(k), str(v)) for k, v in url_params.items()],
                    doseq=True,
                )
            except Exception:
                encoded = ""
            if encoded:
                url = url + ("&" if "?" in url else "?") + encoded

        # GraphQL support (metadata-driven): a tool whose input_schema declares
        # the ``x-graphql-query`` extension (a GraphQL query template using
        # ``$variable`` names) POSTs ``{"query": <template>, "variables":
        # <inputs>}`` — the standard GraphQL contract (e.g. AniList). No
        # hardcoded queries anywhere: the template IS the tool metadata.
        graphql_query: str | None = None
        if isinstance(tool.input_schema, dict):
            _gq = tool.input_schema.get("x-graphql-query")
            if isinstance(_gq, str) and _gq.strip():
                graphql_query = _gq.strip()

        # Use the pooled httpx.AsyncClient (self._client)
        # NOTE: never pass ``params=`` — httpx merges/REPLACES the URL's
        # existing query string (wiping it) when params is given.
        request_kwargs: dict[str, Any] = {
            "headers": headers,
            "follow_redirects": False,  # C1/P0-C: redirects are followed
            # manually with per-hop sandbox re-validation.
        }
        try:
            from nexus.execution.policy import policy_for_capability

            _timeout_s = float(policy_for_capability(tool.name).timeout_s)
        except Exception:
            _timeout_s = float(self._tool_timeout_s)
        if _timeout_s > 0:
            request_kwargs["timeout"] = httpx.Timeout(_timeout_s)

        # FINAL-DESTINATION SANDBOX CHECK (C1/P0-C): the URL actually being
        # requested — after template substitution and query merging — is the
        # enforcement point. Whitelist always applies; SSRF hardening
        # applies when the final host differs from the operator-registered
        # host (input-influenced destination) or any input value carried a
        # URL (relay class).
        self._validate_final_url(url, tool.endpoint_url, inputs)

        response = await self._send_request(
            url, method, request_kwargs, graphql_query, url_params,
        )
        # MANUAL REDIRECT FOLLOWING (C1/P0-C): every hop is re-validated
        # against the sandbox BEFORE the next request — a redirect to an
        # internal/metadata address is blocked, never followed.
        for _hop in range(5):
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            location = response.headers.get("location")
            if not location:
                break
            next_url = str(httpx.URL(url).join(location))
            self._validate_final_url(next_url, tool.endpoint_url, inputs)
            if response.status_code in (301, 302, 303):
                method = "get"
                request_kwargs.pop("json", None)
            url = next_url
            response = await self._send_request(
                url, method, request_kwargs, graphql_query, url_params,
            )

        # Raise HTTPStatusError for 4xx/5xx so the retry policy catches it.
        # NOTE: httpx >=0.28 raises for 3xx too — with ``follow_redirects=True``
        # a real redirect is already followed; an unfollowable 3xx (no
        # Location) must NOT be treated as a retryable transport failure.
        if response.status_code >= 400:
            response.raise_for_status()
        return response

    def _validate_final_url(
        self,
        url: str,
        registered_url: str,
        inputs: dict[str, Any],
    ) -> None:
        """Final-destination sandbox enforcement (C1/P0-C).

        Validates the URL that will actually be requested: the host
        whitelist ALWAYS applies; SSRF hardening applies when the final
        host differs from the operator-registered host (the input-influenced
        destination class) or when any input value carried a URL (the relay
        class). Raises ``SandboxBlockedError`` before any connection.
        """
        from urllib.parse import urlparse  # noqa: PLC0415

        _reg_host = (urlparse(registered_url).hostname or "").lower()
        _final_host = (urlparse(url).hostname or "").lower()
        _input_urls = any(
            isinstance(v, str) and "://" in v
            for v in (inputs or {}).values()
        )
        check_allowed_host(
            url,
            self._sandbox_config.allowed_hosts,
            enforce_ssrf=(_final_host != _reg_host or _input_urls),
        )

    async def _send_request(
        self,
        url: str,
        method: str,
        request_kwargs: dict[str, Any],
        graphql_query: str | None,
        url_params: dict[str, Any],
    ) -> httpx.Response:
        """Dispatch a single request (GET or method + body/GraphQL)."""
        if method == "get":
            return await self._client.get(url, **request_kwargs)
        if graphql_query is not None:
            # GraphQL contract: query template + variables in the body.
            request_kwargs["json"] = {
                "query": graphql_query,
                "variables": dict(url_params),
            }
        else:
            request_kwargs["json"] = url_params
        return await self._client.request(method.upper(), url, **request_kwargs)

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
            data: dict = {"raw": raw[:2000]} if raw else {}
            if raw and raw.strip():
                try:
                    parsed = response.json()
                    if isinstance(parsed, dict):
                        data = parsed
                    elif isinstance(parsed, list):
                        data = {"results": parsed}
                except (json.JSONDecodeError, ValueError):
                    data = {"raw": raw[:2000]}

            error_msg = None
            if not response.is_success:
                error_msg = f"HTTP {response.status_code}"
                if raw:
                    error_msg += f": {raw[:200]}"
                # ERROR BODY IS NOT DATA: an error payload must never flow
                # downstream as a successful tool result. Keep the parsed body
                # only inside ``raw_response_excerpt`` for diagnostics.
                data = {"error": error_msg}
            return ToolResult(
                tool_id=tool.id,
                tool_name=tool.name,
                status="success" if response.is_success else "error",
                http_status=response.status_code,
                data=data,
                error=error_msg,
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
        """Write a ``ToolExecution`` row to the database and update reliability.

        FK-REPAIR (P2-E): the row's ``tool_id`` must reference the REGISTRY
        tool identity. The zero-UUID synthetic stub id (used by the executor
        when a tool has no registry row) is NOT a registry identity — writing
        it violates ``fk_tool_execution_tool_id_tool`` and silently loses
        the execution record. Such rows are SKIPPED with a typed warning
        (never a crash, never a synthetic FK): an unregistered tool produces
        no execution row until it is registered, and the observability gap
        is loud instead of silent.
        """
        if str(getattr(tool, "id", "")) == _ZERO_UUID:
            logger.warning(
                "tool.persist_skipped_unregistered",
                tool=tool.name,
                reason="zero-UUID stub id is not a registry tool identity",
            )
            return
        # Normalize empty-string UUIDs to None — asyncpg rejects '' for UUID
        # columns, and a missing run id is valid (nullable).
        agent_run_id = context.agent_run_id
        if agent_run_id == "":
            agent_run_id = None
        execution = ToolExecution(
            tool_id=tool.id,
            session_id=context.session_id,
            agent_run_id=agent_run_id,
            execution_key=getattr(context, "execution_key", None),
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
        # FK-REPAIR (P2-E): COMMIT the write here. The caller's
        # ``async with session`` context manager does NOT commit on clean
        # exit in this stack (verified: flushed rows were rolled back on
        # close — tool_execution stayed empty while execution succeeded).
        # The persist function owns the write; it must complete it.
        await session.commit()

        # Fire-and-forget EWMA reliability update (non-blocking)
        # Uses tool name as the provider proxy — the capability resolver
        # conventionally names providers the same as their capability.
        _update = __import__("nexus.metrics.store", fromlist=["update_provider_reliability"]).update_provider_reliability  # type: ignore[attr-defined]  # noqa: E501
        asyncio.ensure_future(_update(
            provider_name=tool.name,
            success=result.status == "success",
        ))

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
