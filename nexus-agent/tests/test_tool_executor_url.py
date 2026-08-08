"""Regression tests for ToolExecutor URL templating.

Guards the two historical failures behind ``get_current_weather``:

1. ``params={}`` used to be passed to httpx unconditionally — httpx MERGES
   the empty dict onto the URL and wipes its query string, so the request
   went out as a bare path (``/v1/forecast``) and the API answered 200 with
   an empty body.
2. URL template placeholders not present in inputs (e.g. a schema ``default``
   parameter the planner omitted) used to be sent literally as ``{name}``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from nexus.tools.executor import ToolExecutor, _effective_max_attempts
from nexus.tools.schemas import ToolRead

_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={latitude}&longitude={longitude}&current_weather={current_weather}"
)

_SCHEMAS: dict[str, dict] = {
    "input": {
        "type": "object",
        "required": ["latitude", "longitude"],
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "current_weather": {"type": "boolean", "default": True},
        },
    },
    "output": {
        "type": "object",
        "required": ["latitude", "longitude", "current_weather"],
        "properties": {
            "latitude": {"type": "number"},
            "longitude": {"type": "number"},
            "current_weather": {"type": "object"},
        },
    },
}

_OK_BODY = {
    "latitude": 31.52,
    "longitude": 74.35,
    "current_weather": {"temperature": 31.5, "windspeed": 6.7},
}


class _RecordingClient:
    """Stub httpx client that records the exact request it would send."""

    def __init__(self, body: dict) -> None:
        self.body = body
        self.request_url: str | None = None
        self.params_kwarg: object = "unset"

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        self.request_url = url
        self.params_kwarg = kwargs.get("params")
        return httpx.Response(
            200,
            json=self.body,
            request=httpx.Request("GET", url),
        )

    async def aclose(self) -> None:  # pragma: no cover - trivial
        return None


def _tool() -> ToolRead:
    now = datetime.now(UTC).isoformat()
    return ToolRead(
        id="00000000-0000-0000-0000-000000000000",
        name="get_current_weather",
        description="",
        purpose="",
        tool_type="http_api",
        endpoint_url=_URL,
        http_method="GET",
        auth_type="none",
        auth_ref="",
        input_schema=_SCHEMAS["input"],
        output_schema=_SCHEMAS["output"],
        validation_rules={},
        examples=[],
        tags=[],
        category="general",
        requires_approval=False,
        risk_level="low",
        enabled=True,
        version=1,
        created_at=now,
        updated_at=now,
    )



async def test_query_string_survives_when_no_extra_params(monkeypatch):
    """The URL's query string must not be wiped by an empty params dict."""
    # Hermetic: Redis clients are event-loop-bound and pytest-asyncio reuses
    # the module-level client across different loops — the executor must not
    # touch Redis here (event publishing is skipped when the client is None).
    monkeypatch.setattr("nexus.tools.executor.get_redis_client", lambda: None)
    client = _RecordingClient(_OK_BODY)
    executor = ToolExecutor(http_client=client)  # type: ignore[arg-type]
    try:
        result = await executor.execute(
            tool=_tool(),
            inputs={"latitude": 31.5204, "longitude": "74.3587"},
            context=executor_exec_context(),
            session=None,  # type: ignore[arg-type]
            skip_approval=True,
        )
    finally:
        await executor.close()

    assert client.request_url == (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=31.5204&longitude=74.3587&current_weather=true"
    ), f"params kwarg sent: {client.params_kwarg!r}"
    assert client.params_kwarg is None
    assert result.status == "success"

    # Same client/executor/loop: extra (non-placeholder) params must still be
    # forwarded on a second call — merged INTO the URL query string. httpx's
    # ``params=`` kwarg REPLACES a URL's existing query (wiping latitude/
    # longitude), so the executor merges instead: everything stays on the
    # wire, nothing is lost.
    await executor.execute(
        tool=_tool(),
        inputs={"latitude": 31.5, "longitude": 74.3, "forecast_days": 3},
        context=executor_exec_context(),
        session=None,  # type: ignore[arg-type]
        skip_approval=True,
    )
    assert "forecast_days=3" in client.request_url
    assert "latitude=31.5" in client.request_url
    assert client.params_kwarg is None


def executor_exec_context():
    from nexus.tools.executor import ExecutionContext

    return ExecutionContext(session_id="00000000-0000-0000-0000-000000000000")


def test_effective_max_attempts_idempotent_retries():
    """Idempotent tools retry the configured number of times (safe)."""
    assert _effective_max_attempts(True, max_retries=2) == 3
    assert _effective_max_attempts(True, max_retries=0) == 1


def test_effective_max_attempts_non_idempotent_single_attempt():
    """Non-idempotent tools are NEVER retried — a retried call may duplicate
    an already-fired side effect. One attempt only, regardless of settings."""
    assert _effective_max_attempts(False, max_retries=2) == 1
    assert _effective_max_attempts(False, max_retries=5) == 1


def _path_tool(required: bool = False) -> ToolRead:
    """Tool with a ``/posts/{id}``-style path template (string-typed id —
    the null-sentinel must pass schema validation to reach the URL stage)."""
    now = datetime.now(UTC).isoformat()
    input_schema = {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "Record id"}},
        **( {"required": ["id"]} if required else {} ),
    }
    return ToolRead(
        id="00000000-0000-0000-0000-00000000000f",
        name="jsonplaceholder_request",
        description="",
        purpose="",
        tool_type="http_api",
        endpoint_url="https://jsonplaceholder.typicode.com/posts/{id}",
        http_method="GET",
        auth_type="none",
        auth_ref="",
        input_schema=input_schema,
        output_schema=_SCHEMAS["output"],
        validation_rules={},
        examples=[],
        tags=[],
        category="general",
        requires_approval=False,
        risk_level="low",
        enabled=True,
        version=1,
        created_at=now,
        updated_at=now,
    )


async def test_null_sentinel_never_fills_path_segment(monkeypatch):
    """A ``"None"`` string (unresolved placeholder artifact) must never be
    sent as a literal path segment — ``/posts/None`` 404s instead of an
    honest absent-parameter result."""
    monkeypatch.setattr("nexus.tools.executor.get_redis_client", lambda: None)
    client = _RecordingClient(_OK_BODY)
    executor = ToolExecutor(http_client=client)  # type: ignore[arg-type]
    try:
        result = await executor.execute(
            tool=_path_tool(),
            inputs={"id": "None"},
            context=executor_exec_context(),
            session=None,  # type: ignore[arg-type]
            skip_approval=True,
        )
    finally:
        await executor.close()

    assert "None" not in client.request_url, f"sent literal None: {client.request_url}"
    assert result.status == "success"
    assert client.request_url == "https://jsonplaceholder.typicode.com/posts"


async def test_literal_unresolved_placeholder_never_fills_segment(monkeypatch):
    """A literal ``${...}`` (upstream resolution failure) must not be sent —
    optional segments are stripped, required ones raise explicitly."""
    monkeypatch.setattr("nexus.tools.executor.get_redis_client", lambda: None)
    client = _RecordingClient(_OK_BODY)
    executor = ToolExecutor(http_client=client)  # type: ignore[arg-type]
    try:
        result = await executor.execute(
            tool=_path_tool(),
            inputs={"id": "${foo.result.id}"},
            context=executor_exec_context(),
            session=None,  # type: ignore[arg-type]
            skip_approval=True,
        )
    finally:
        await executor.close()

    assert "${" not in client.request_url
    assert result.status == "success"
    assert client.request_url == "https://jsonplaceholder.typicode.com/posts"


async def test_required_path_param_with_null_sentinel_raises(monkeypatch):
    """With the path param declared REQUIRED, a null-sentinel value must
    raise explicitly (the request cannot be formed) — never ``/posts/None``."""
    import pytest

    monkeypatch.setattr("nexus.tools.executor.get_redis_client", lambda: None)
    client = _RecordingClient(_OK_BODY)
    executor = ToolExecutor(http_client=client)  # type: ignore[arg-type]
    try:
        with pytest.raises(ValueError, match="Missing required path parameter"):
            await executor.execute(
                tool=_path_tool(required=True),
                inputs={"id": "None"},
                context=executor_exec_context(),
                session=None,  # type: ignore[arg-type]
                skip_approval=True,
            )
    finally:
        await executor.close()
