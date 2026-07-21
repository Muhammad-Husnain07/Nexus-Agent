"""LLM client wrapping LiteLLM for completions and embeddings."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import litellm
from pydantic import BaseModel, Field

from nexus.llm.provider import ProviderRegistry

log = logging.getLogger(__name__)

# Cache of Ollama model name → capabilities (fetched from /api/tags at runtime)
_ollama_capabilities: dict[str, set[str]] = {}
# Simple template for models that don't support the chat API natively
_RAW_TEMPLATE = (
    "{system}"
    "{user}"
)

_LITELLM_TEMPERATURE: float = 0.7


async def _ollama_supports_tools(model: str, api_base: str) -> bool:
    """Check if an Ollama model supports the chat API with tool calls.

    Fetches model capabilities from ``/api/tags`` at runtime and caches
    the result.  No hardcoded model names — works for any Ollama model.
    """
    if model in _ollama_capabilities:
        return "tools" in _ollama_capabilities[model]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{api_base}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                for entry in data.get("models", []):
                    name: str = entry.get("name", "")
                    caps: list[str] = entry.get("capabilities", [])
                    _ollama_capabilities[name] = set(caps)
                    # Also cache without tag (e.g. "Qwen3:4B" and "Qwen3")
                    base = name.split(":")[0]
                    if base not in _ollama_capabilities:
                        _ollama_capabilities[base] = set(caps)

        cached = _ollama_capabilities.get(model, set())
        return "tools" in cached
    except Exception as exc:
        log.warning("Failed to fetch Ollama capabilities for %s: %s", model, exc)
        return True  # assume chat API works on error rather than breaking


class UsageInfo(BaseModel):
    """Token usage information for an LLM response."""

    prompt_tokens: int = Field(default=0, description="Tokens in the prompt")
    completion_tokens: int = Field(default=0, description="Tokens in the completion")
    total_tokens: int = Field(default=0, description="Total tokens consumed")


class LLMResponse(BaseModel):
    """A complete (non-streaming) response from an LLM call."""

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
    """A single streaming chunk from an LLM response."""

    delta_content: str | None = Field(default=None, description="Text content delta")
    delta_tool_calls: list[dict[str, Any]] | None = Field(
        default=None, description="Tool call deltas"
    )
    finish_reason: str | None = Field(default=None, description="Finish reason if final chunk")


def _format_raw_prompt(messages: list[dict[str, Any]]) -> str:
    """Concatenate messages into a flat prompt for models without chat API support."""
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"System: {content}\n")
        elif role == "user":
            parts.append(f"User: {content}\n")
        elif role == "assistant":
            parts.append(f"Assistant: {content}\n")
        elif role == "tool":
            parts.append(f"Tool result: {content}\n")
    parts.append("Assistant: ")
    return "".join(parts)


@dataclass
class LLMClient:
    """Unified client for LLM completions and embeddings via LiteLLM.

    Wraps ``litellm.acompletion`` and ``litellm.acompletion_stream`` with
    provider resolution, cost tracking, and optional caching.
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

        For Ollama models, the client dynamically detects whether the model
        supports the chat API with tool calls (via ``/api/tags`` capabilities).
        Models with ``"tools"`` capability use the native chat API.  Older
        models without tool support fall back to raw mode with a flat prompt.

        Args:
            model: Model identifier (e.g. gpt-4o, ollama/Qwen3:4B).
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

        # Ensure model is prefixed with provider name for LiteLLM routing
        if "/" not in model and provider.config.base_url:
            model = f"{provider_name}/{model}"
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if provider.config.base_url:
            kwargs["api_base"] = provider.config.base_url
        api_key_val = provider.api_key.get_secret_value()
        if api_key_val:
            kwargs["api_key"] = api_key_val

        # Ollama-specific handling — dynamically detect chat API support
        if provider_name == "ollama":
            kwargs["keep_alive"] = "30m"
            supports_tools = await _ollama_supports_tools(model, provider.config.base_url or "")
            if not supports_tools:
                # Fallback to raw mode for models without tool support
                kwargs["extra_body"] = {"raw": True}
                prompt = _format_raw_prompt(messages)
                kwargs["messages"] = [{"role": "user", "content": prompt}]
                kwargs.pop("response_format", None)

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

        Raises:
            ValueError: If the returned embedding dimension does not match
                the configured ``embedding_dimensions``.
        """
        from litellm import aembedding  # noqa: PLC0415

        from nexus.config.settings import get_settings  # noqa: PLC0415

        settings = get_settings()
        provider, provider_name = self.registry.resolve_provider(model)
        if "/" not in model and provider.config.base_url:
            model = f"{provider_name}/{model}"
        kwargs: dict[str, Any] = {
            "model": model,
            "input": texts,
        }
        if provider.config.base_url:
            kwargs["api_base"] = provider.config.base_url
        api_key_val = provider.api_key.get_secret_value()
        if api_key_val:
            kwargs["api_key"] = api_key_val

        if provider.config.supports_output_dimensions:
            kwargs["dimensions"] = settings.llm.embedding_dimensions

        response = await aembedding(**kwargs)
        embeddings = [item["embedding"] for item in response.data]

        expected = settings.llm.embedding_dimensions
        for i, vec in enumerate(embeddings):
            actual = len(vec)
            if actual != expected:
                raise ValueError(
                    f"Embedding model '{model}' returned a {actual}-dim vector "
                    f"but NEXUS_LLM__EMBEDDING_DIMENSIONS={expected}. "
                    f"Either change the embedding model or update the setting "
                    f"and run: uv run python scripts/rebuild_embedding_dim.py {actual}"
                )

        return embeddings

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
