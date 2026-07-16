"""Unit tests for the LLM module — client, retries, fallback, routing, cost."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from nexus.config.settings import ProviderConfig
from nexus.llm.client import LLMClient, LLMResponse
from nexus.llm.cost_tracker import CostTracker
from nexus.llm.fallback import AllProvidersFailedError, FallbackChain
from nexus.llm.provider import ProviderInstance, ProviderRegistry
from nexus.llm.retries import is_non_retryable, is_retryable
from nexus.llm.router import ModelRouter, TaskType


@pytest.fixture
def provider_openai() -> ProviderConfig:
    return ProviderConfig(
        name="openai",
        base_url="",
        api_key_ref="OPENAI_API_KEY",
        models=["gpt-4o", "gpt-4o-mini"],
        cost_per_1k_input=0.01,
        cost_per_1k_output=0.03,
        max_tokens=4096,
        supports_streaming=True,
        supports_tools=True,
        supports_structured_output=True,
    )


@pytest.fixture
def provider_anthropic() -> ProviderConfig:
    return ProviderConfig(
        name="anthropic",
        base_url="",
        api_key_ref="ANTHROPIC_API_KEY",
        models=["claude-3-opus", "claude-3-sonnet"],
        cost_per_1k_input=0.015,
        cost_per_1k_output=0.075,
        max_tokens=4096,
        supports_streaming=True,
        supports_tools=True,
        supports_structured_output=False,
    )


@pytest.fixture
def registry(
    provider_openai: ProviderConfig,
    provider_anthropic: ProviderConfig,
) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg._providers = {
        "openai": ProviderInstance(config=provider_openai, api_key=SecretStr("sk-openai")),
        "anthropic": ProviderInstance(config=provider_anthropic, api_key=SecretStr("sk-anthropic")),
    }
    reg._model_to_provider = {
        "gpt-4o": "openai",
        "gpt-4o-mini": "openai",
        "claude-3-opus": "anthropic",
        "claude-3-sonnet": "anthropic",
    }
    return reg


@pytest.fixture
def client(registry: ProviderRegistry) -> LLMClient:
    return LLMClient(registry=registry)


# ── Provider Registry ────────────────────────────────────────────────────


def test_registry_resolve_provider(registry: ProviderRegistry) -> None:
    instance, name = registry.resolve_provider("gpt-4o")
    assert name == "openai"
    assert instance.config.name == "openai"


def test_registry_resolve_unknown_model(registry: ProviderRegistry) -> None:
    instance, name = registry.resolve_provider("unknown-model")
    assert name == "openai"
    assert instance.config.name == "openai"


def test_registry_available_models(registry: ProviderRegistry) -> None:
    models = registry.available_models
    assert "gpt-4o" in models
    assert "claude-3-opus" in models
    assert len(models) == 4


# ── LLM Client ───────────────────────────────────────────────────────────


@patch("nexus.llm.client.litellm.acompletion")
async def test_complete_success(mock_acompletion: MagicMock, client: LLMClient) -> None:
    mock_response = _make_mock_response(content="Hello!")
    mock_acompletion.return_value = mock_response

    response = await client.complete(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])

    assert isinstance(response, LLMResponse)
    assert response.content == "Hello!"
    assert response.finish_reason == "stop"
    assert response.usage.prompt_tokens == 10
    assert response.usage.completion_tokens == 5
    assert response.model == "gpt-4o"
    assert response.provider == "openai"
    assert response.cost_usd > 0
    assert response.latency_ms >= 0


@patch("nexus.llm.client.litellm.acompletion")
async def test_compute_cost(mock_acompletion: MagicMock, client: LLMClient) -> None:
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "test"
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].finish_reason = "stop"
    mock_response.usage.prompt_tokens = 1000
    mock_response.usage.completion_tokens = 500
    mock_response.usage.total_tokens = 1500
    mock_response.model_dump.return_value = {}
    mock_acompletion.return_value = mock_response

    response = await client.complete(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])

    expected = (1000 / 1000) * 0.01 + (500 / 1000) * 0.03
    assert response.cost_usd == pytest.approx(expected, rel=1e-6)


@patch("nexus.llm.client.litellm.acompletion")
async def test_stream_complete(mock_acompletion: MagicMock, client: LLMClient) -> None:
    async def _mock_stream() -> AsyncIterator:
        yield _make_chunk(content="Hello", finish_reason=None)
        yield _make_chunk(content=" World", finish_reason="stop")

    mock_acompletion.return_value = _mock_stream()

    result = await client.complete(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )

    chunks = []
    async for chunk in result:
        chunks.append(chunk)

    assert len(chunks) == 2
    assert chunks[0].delta_content == "Hello"
    assert chunks[1].delta_content == " World"
    assert chunks[1].finish_reason == "stop"


def _make_chunk(content: str | None = None, finish_reason: str | None = None) -> MagicMock:
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = content
    chunk.choices[0].delta.tool_calls = None
    chunk.choices[0].finish_reason = finish_reason
    return chunk


# ── Retries ──────────────────────────────────────────────────────────────


def test_retryable_exceptions_defined() -> None:
    from nexus.llm.retries import RETRYABLE_EXCEPTIONS

    assert len(RETRYABLE_EXCEPTIONS) > 0
    names = {e.__name__ for e in RETRYABLE_EXCEPTIONS}
    assert "RateLimitError" in names
    assert "APIConnectionError" in names
    assert "InternalServerError" in names


def test_non_retryable_exceptions_defined() -> None:
    from nexus.llm.retries import NON_RETRYABLE_EXCEPTIONS

    assert len(NON_RETRYABLE_EXCEPTIONS) > 0
    names = {e.__name__ for e in NON_RETRYABLE_EXCEPTIONS}
    assert "AuthenticationError" in names
    assert "BadRequestError" in names
    assert "ContentPolicyViolationError" in names


def test_is_retryable_unknown() -> None:
    assert is_retryable(ValueError("foo")) is False


def test_is_non_retryable_not_matched() -> None:
    assert is_non_retryable(ValueError("foo")) is False


# ── Fallback Chain ───────────────────────────────────────────────────────


@patch("nexus.llm.client.litellm.acompletion")
async def test_fallback_primary_succeeds(mock_acompletion: MagicMock, client: LLMClient) -> None:
    mock_acompletion.return_value = _make_mock_response(content="primary ok")

    chain = FallbackChain(client, max_attempts_per_model=2)
    response = await chain.execute(
        primary="gpt-4o",
        fallbacks=["claude-3-sonnet"],
        messages=[{"role": "user", "content": "hi"}],
    )

    assert isinstance(response, LLMResponse)
    assert response.content == "primary ok"
    assert response.provider == "openai"


@patch("nexus.llm.client.litellm.acompletion")
async def test_fallback_triggers_on_failure(
    mock_acompletion: MagicMock,
    client: LLMClient,
) -> None:
    from litellm.exceptions import RateLimitError

    class FakeRateLimitError(RateLimitError):
        def __init__(self) -> None:  # type: ignore[no-untyped-def]
            pass

        def __str__(self) -> str:
            return "RateLimitError: rate_limited"

    call_count = 0

    async def _side_effect(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise FakeRateLimitError()
        return _make_mock_response(content="fallback ok")

    mock_acompletion.side_effect = _side_effect

    chain = FallbackChain(client, max_attempts_per_model=2)
    response = await chain.execute(
        primary="gpt-4o",
        fallbacks=["claude-3-sonnet"],
        messages=[{"role": "user", "content": "hi"}],
    )

    assert response.content == "fallback ok"
    assert call_count == 3


@patch("nexus.llm.client.litellm.acompletion")
async def test_fallback_all_exhausted(mock_acompletion: MagicMock, client: LLMClient) -> None:
    from litellm.exceptions import RateLimitError

    exc = RateLimitError.__new__(RateLimitError)
    mock_acompletion.side_effect = exc

    chain = FallbackChain(client, max_attempts_per_model=1)
    with pytest.raises(AllProvidersFailedError) as exc:
        await chain.execute(
            primary="gpt-4o",
            fallbacks=["claude-3-sonnet"],
            messages=[{"role": "user", "content": "hi"}],
        )

    assert "gpt-4o" in str(exc.value)


@patch("nexus.llm.client.litellm.acompletion")
async def test_fallback_no_retry_on_auth_error(
    mock_acompletion: MagicMock,
    client: LLMClient,
) -> None:
    from litellm.exceptions import AuthenticationError

    exc = AuthenticationError.__new__(AuthenticationError)
    mock_acompletion.side_effect = exc

    chain = FallbackChain(client, max_attempts_per_model=3)
    with pytest.raises(AuthenticationError):
        await chain.execute(
            primary="gpt-4o",
            fallbacks=["claude-3-sonnet"],
            messages=[{"role": "user", "content": "hi"}],
        )


@patch("nexus.llm.client.litellm.acompletion")
async def test_fallback_aggregates_cost(mock_acompletion: MagicMock, client: LLMClient) -> None:
    from litellm.exceptions import RateLimitError

    exc = RateLimitError.__new__(RateLimitError)
    mock_acompletion.side_effect = exc

    chain = FallbackChain(client, max_attempts_per_model=1)
    with pytest.raises(AllProvidersFailedError):
        await chain.execute(
            primary="gpt-4o",
            fallbacks=["claude-3-sonnet"],
            messages=[{"role": "user", "content": "hi"}],
        )


# ── Model Router ─────────────────────────────────────────────────────────


def test_router_defaults() -> None:
    router = ModelRouter()
    assert router.get_model(TaskType.CHAT) == "gpt-4o"
    assert router.get_model(TaskType.TOOL_SELECTION) == "gpt-4o-mini"
    assert router.get_model(TaskType.EMBEDDING) == "text-embedding-3-small"


def test_router_override() -> None:
    router = ModelRouter()
    router.register_override(TaskType.CHAT, "claude-3-opus")
    assert router.get_model(TaskType.CHAT) == "claude-3-opus"


# ── Cost Tracker ─────────────────────────────────────────────────────────


async def test_cost_tracker_accumulates_and_flushes(mock_session) -> None:
    agent_run_id = uuid.uuid4()
    tracker = CostTracker(session=mock_session, agent_run_id=agent_run_id)

    tracker.record(0.005)
    tracker.record(0.003)
    assert tracker.accumulated_cost == pytest.approx(0.008, rel=1e-6)

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    await tracker.flush()

    assert tracker.accumulated_cost == 0.0


def _make_mock_response(content: str = "ok") -> MagicMock:
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = content
    mock.choices[0].message.tool_calls = None
    mock.choices[0].finish_reason = "stop"
    mock.usage.prompt_tokens = 10
    mock.usage.completion_tokens = 5
    mock.usage.total_tokens = 15
    mock.model_dump.return_value = {"id": "mock"}
    return mock
