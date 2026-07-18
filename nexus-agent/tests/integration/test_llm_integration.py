"""Integration tests for the LLM module — mocked LiteLLM with multiple providers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from litellm.exceptions import AuthenticationError, RateLimitError

from nexus.config.settings import LLMSettings, ProviderConfig, Settings
from nexus.llm.client import LLMClient, LLMResponse
from nexus.llm.fallback import AllProvidersFailedError, FallbackChain
from nexus.llm.provider import ProviderRegistry


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm=LLMSettings(
            default_provider="openai",
            default_model="gpt-4o",
            providers=[
                ProviderConfig(
                    name="openai",
                    api_key_ref="OPENAI_API_KEY",
                    models=["gpt-4o", "gpt-4o-mini"],
                    cost_per_1k_input=0.01,
                    cost_per_1k_output=0.03,
                ),
                ProviderConfig(
                    name="anthropic",
                    api_key_ref="ANTHROPIC_API_KEY",
                    models=["claude-3-sonnet"],
                    cost_per_1k_input=0.015,
                    cost_per_1k_output=0.075,
                ),
            ],
        ),
        observability={"langsmith_api_key": None},
        auth={"jwt_secret": "test"},
    )


@pytest.fixture
def registry(settings: Settings) -> ProviderRegistry:
    with patch("nexus.llm.provider.get_settings", return_value=settings):
        return ProviderRegistry.init()


@pytest.fixture
def client(registry: ProviderRegistry) -> LLMClient:
    return LLMClient(registry=registry)


def _make_mock_response(
    content: str = "hello",
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
    model: str = "gpt-4o",
) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens

    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message.content = content
    choice.message.tool_calls = None

    response = MagicMock(spec=["choices", "usage", "model_dump"])
    response.choices = [choice]
    response.usage = usage
    response.model_dump.return_value = {"id": "mock", "object": "chat.completion"}
    return response


class FakeRateLimitError(RateLimitError):
    """Subclass that avoids litellm's hanging __init__ on Windows."""

    def __init__(self, message: str = "") -> None:  # type: ignore[no-untyped-def]
        self.message = message

    def __str__(self) -> str:
        return f"RateLimitError: {self.message}"


class FakeAuthError(AuthenticationError):
    """Subclass that avoids litellm's hanging __init__ on Windows."""

    def __init__(self, message: str = "") -> None:  # type: ignore[no-untyped-def]
        self.message = message

    def __str__(self) -> str:
        return f"AuthenticationError: {self.message}"


@patch("nexus.llm.client.litellm.acompletion")
async def test_complete_with_cost(
    mock_acompletion: AsyncMock,
    client: LLMClient,
) -> None:
    """Two providers configured; cost computed correctly per-provider."""
    mock_response = _make_mock_response(
        content="from openai",
        prompt_tokens=100,
        completion_tokens=50,
    )
    mock_acompletion.return_value = mock_response

    result = await client.complete(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert isinstance(result, LLMResponse)
    assert result.content == "from openai"
    assert result.provider == "openai"
    # 100/1000 * 0.01 + 50/1000 * 0.03 = 0.001 + 0.0015 = 0.0025
    assert result.cost_usd == 0.0025


@patch("nexus.llm.client.litellm.acompletion")
async def test_fallback_on_rate_limit(
    mock_acompletion: AsyncMock,
    client: LLMClient,
) -> None:
    """Fallback triggers on RateLimitError — falls through to claude."""
    calls: list[int] = []

    async def side_effect(**kwargs: object) -> MagicMock:
        calls.append(1)
        if len(calls) == 1:
            raise FakeRateLimitError("rate_limited")
        return _make_mock_response(content="from claude", model="claude-3-sonnet")

    mock_acompletion.side_effect = side_effect

    chain = FallbackChain(client, max_attempts_per_model=1)
    result = await chain.execute(
        primary="gpt-4o",
        fallbacks=["claude-3-sonnet"],
        messages=[{"role": "user", "content": "hi"}],
    )

    assert isinstance(result, LLMResponse)
    assert result.content == "from claude"
    assert len(calls) == 2


@patch("nexus.llm.client.litellm.acompletion")
async def test_no_retry_on_auth_error(
    mock_acompletion: AsyncMock,
    client: LLMClient,
) -> None:
    """AuthenticationError is NOT retried — raised immediately."""
    mock_acompletion.side_effect = FakeAuthError("bad key")

    chain = FallbackChain(client, max_attempts_per_model=2)
    with pytest.raises(FakeAuthError):
        await chain.execute(
            primary="gpt-4o",
            fallbacks=["claude-3-sonnet"],
            messages=[{"role": "user", "content": "hi"}],
        )

    # Should fail on the first call, not retry
    assert mock_acompletion.call_count == 1


@patch("nexus.llm.client.litellm.acompletion")
async def test_all_providers_exhausted(
    mock_acompletion: AsyncMock,
    client: LLMClient,
) -> None:
    """Raises AllProvidersFailedError when all models fail."""
    mock_acompletion.side_effect = FakeRateLimitError("down")

    chain = FallbackChain(client, max_attempts_per_model=1)
    with pytest.raises(AllProvidersFailedError) as exc_info:
        await chain.execute(
            primary="gpt-4o",
            fallbacks=["claude-3-sonnet"],
            messages=[{"role": "user", "content": "hi"}],
        )

    assert "gpt-4o" in str(exc_info.value)
    assert mock_acompletion.call_count == 2  # one per model
