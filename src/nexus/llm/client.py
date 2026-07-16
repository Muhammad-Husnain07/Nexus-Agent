"""LLM client wrapping LiteLLM for completions and embeddings."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import litellm
from pydantic import BaseModel, Field

from nexus.llm.provider import ProviderRegistry

_LITELLM_TEMPERATURE: float = 0.7


class UsageInfo(BaseModel):
    """Token usage information for an LLM response.

    Attributes:
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the completion.
        total_tokens: Sum of prompt and completion tokens.
    """

    prompt_tokens: int = Field(default=0, description="Tokens in the prompt")
    completion_tokens: int = Field(default=0, description="Tokens in the completion")
    total_tokens: int = Field(default=0, description="Total tokens consumed")


class LLMResponse(BaseModel):
    """A complete (non-streaming) response from an LLM call.

    Attributes:
        content: The response text content.
        tool_calls: List of tool call invocations, if any.
        usage: Token usage breakdown.
        finish_reason: Reason the generation finished (stop, length, tool_calls).
        raw_response: The full raw response from LiteLLM.
        model: The model identifier used.
        provider: The provider name that served the request.
        latency_ms: Total request latency in milliseconds.
        cost_usd: Computed cost in USD based on token usage and provider pricing.
    """

    content: str | None = Field(default=None, description="Response text content")
    tool_calls: list[dict[str, Any]] | None = Field(
        default=None, description="Tool call invocations"
    )
    usage: UsageInfo = Field(default_factory=UsageInfo, description="Token usage")
    finish_reason: str | None = Field(default=None, description="Reason generation finished")
    raw_response: dict[str, Any] = Field(default_factory=dict, description="Raw LiteLLM response")
    model: str = Field(default="", description="Model identifier used")
    provider: str = Field(default="", description="Provider name")
    latency_ms: float = Field(default=0.0, description="Request latency in milliseconds")
    cost_usd: float = Field(default=0.0, description="Computed cost in USD")


class LLMChunk(BaseModel):
    """A single streaming chunk from an LLM response.

    Attributes:
        delta_content: Text content delta for this chunk.
        delta_tool_calls: Tool call deltas for this chunk.
        finish_reason: Finish reason if this is the final chunk.
    """

    delta_content: str | None = Field(default=None, description="Text content delta")
    delta_tool_calls: list[dict[str, Any]] | None = Field(
        default=None, description="Tool call deltas"
    )
    finish_reason: str | None = Field(default=None, description="Finish reason if final chunk")


@dataclass
class LLMClient:
    """Unified client for LLM completions and embeddings via LiteLLM.

    Wraps ``litellm.acompletion`` and ``litellm.acompletion_stream`` with
    provider resolution, cost tracking, and optional caching.

    Attributes:
        registry: ProviderRegistry for resolving models to providers.
    """

    registry: ProviderRegistry = field(default_factory=ProviderRegistry.get_instance)

    async def complete(  # noqa: PLR0913
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> LLMResponse | AsyncIterator[LLMChunk]:
        """Send a completion request to the LLM.

        Args:
            model: Model identifier (e.g. gpt-4o, claude-3-opus).
            messages: Conversation messages in OpenAI format.
            tools: Optional tool/function definitions.
            response_format: Optional structured output format spec.
            temperature: Sampling temperature (overrides provider default).
            max_tokens: Max tokens (overrides provider default).
            stream: If True, return an async iterator of LLMChunk.

        Returns:
            LLMResponse for non-streaming, or AsyncIterator[LLMChunk] for streaming.
        """
        provider, provider_name = self.registry.resolve_provider(model)
        start = time.monotonic()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if provider.api_key:
            kwargs["api_key"] = provider.api_key.get_secret_value()
        if tools:
            kwargs["tools"] = tools
        if response_format:
            kwargs["response_format"] = response_format
        temp = temperature
        if temp is None:
            temp = getattr(provider.config, "temperature", _LITELLM_TEMPERATURE)
        kwargs["temperature"] = temp
        kwargs["max_tokens"] = max_tokens if max_tokens is not None else provider.config.max_tokens

        if stream:
            return self._stream_complete(kwargs, model, provider_name)
        return await self._complete(kwargs, model, provider_name, start)

    async def _complete(
        self,
        kwargs: dict[str, Any],
        model: str,
        provider_name: str,
        start: float,
    ) -> LLMResponse:
        response = await litellm.acompletion(**kwargs)
        latency_ms = (time.monotonic() - start) * 1000
        return self._build_response(response, model, provider_name, latency_ms)

    async def _stream_complete(
        self,
        kwargs: dict[str, Any],
        model: str,
        provider_name: str,
    ) -> AsyncIterator[LLMChunk]:
        kwargs["stream"] = True
        stream = await litellm.acompletion(**kwargs)
        async for chunk in stream:
            finish_reason = None
            if chunk.choices and chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            delta = chunk.choices[0].delta if chunk.choices else None
            yield LLMChunk(
                delta_content=getattr(delta, "content", None) if delta else None,
                delta_tool_calls=self._extract_delta_tool_calls(delta) if delta else None,
                finish_reason=finish_reason,
            )

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            model: Embedding model identifier.
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors, one per input text.
        """
        from litellm import aembedding  # noqa: PLC0415

        provider, _ = self.registry.resolve_provider(model)
        kwargs: dict[str, Any] = {
            "model": model,
            "input": texts,
        }
        if provider.api_key:
            kwargs["api_key"] = provider.api_key.get_secret_value()

        response = await aembedding(**kwargs)
        return [item["embedding"] for item in response.data]

    def _build_response(
        self,
        response: Any,
        model: str,
        provider_name: str,
        latency_ms: float,
    ) -> LLMResponse:
        choice = response.choices[0] if response.choices else None
        content = getattr(choice, "message", None)

        tool_calls = None
        if content and hasattr(content, "tool_calls") and content.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in content.tool_calls
            ]

        usage = response.usage if hasattr(response, "usage") else None
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0

        cost_usd = self._compute_cost(
            provider_name,
            prompt_tokens,
            completion_tokens,
        )

        return LLMResponse(
            content=getattr(content, "content", None) if content else None,
            tool_calls=tool_calls,
            usage=UsageInfo(
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                total_tokens=total_tokens or 0,
            ),
            finish_reason=getattr(choice, "finish_reason", None) if choice else None,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else {},
            model=model,
            provider=provider_name,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )

    def _compute_cost(
        self,
        provider_name: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        provider = self.registry.get_provider(provider_name)
        if provider is None:
            return 0.0
        input_cost = (prompt_tokens / 1000) * provider.config.cost_per_1k_input
        output_cost = (completion_tokens / 1000) * provider.config.cost_per_1k_output
        return round(input_cost + output_cost, 6)

    @staticmethod
    def _extract_delta_tool_calls(delta: Any) -> list[dict[str, Any]] | None:
        if not hasattr(delta, "tool_calls") or not delta.tool_calls:
            return None
        result: list[dict[str, Any]] = []
        for tc in delta.tool_calls:
            entry: dict[str, Any] = {
                "index": getattr(tc, "index", 0),
            }
            if hasattr(tc, "id") and tc.id:
                entry["id"] = tc.id
            if hasattr(tc, "function"):
                func: dict[str, str] = {}
                if hasattr(tc.function, "name") and tc.function.name:
                    func["name"] = tc.function.name
                if hasattr(tc.function, "arguments") and tc.function.arguments:
                    func["arguments"] = tc.function.arguments
                if func:
                    entry["function"] = func
            result.append(entry)
        return result if result else None
