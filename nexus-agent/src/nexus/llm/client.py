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

# Chat templates for models that need raw mode (thinking models).
# Keyed by model family prefix, values are callables that format messages.
# The template is used when 'raw: true' is sent to Ollama so the model
# still receives properly structured input.
_MODEL_TEMPLATES: dict[str, str] = {
    "qwen": (
        "<|im_start|>system\n{system}<|im_end|>\n"
        "<|im_start|>user\n{user}<|im_end|>\n"
        "<|im_start|>assistant"
    ),
    "qwq": (
        "<|im_start|>system\n{system}<|im_end|>\n"
        "<|im_start|>user\n{user}<|im_end|>\n"
        "<|im_start|>assistant"
    ),
    "deepseek": (
        "<|im_start|>system\n{system}<|im_end|>\n"
        "<|im_start|>user\n{user}<|im_end|>\n"
        "<|im_start|>assistant"
    ),
}

# Cache of model → chat template, populated lazily from Ollama /api/show
_model_template_cache: dict[str, str | None] = {}


async def _fetch_ollama_template(model: str, api_base: str) -> str | None:
    """Fetch a model's native chat template from Ollama and cache it."""
    if model in _model_template_cache:
        return _model_template_cache[model]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{api_base}/api/show", json={"model": model})
            if resp.status_code == 200:
                data = resp.json()
                template = data.get("template") or ""
                if template and "{{ " in template:
                    _model_template_cache[model] = template
                    return template
    except Exception as exc:
        log.warning("Failed to fetch Ollama template for %s: %s", model, exc)
    _model_template_cache[model] = None
    return None


def _extract_template_format(template: str) -> str | None:
    """Convert a Go Ollama template into a Python format string.

    Handles the common pattern:
      {{- range .Messages }}
      {{- if eq .Role "system" }}<|im_start|>system\n{{ .Content }}<|im_end|>
      ...
      {{- end }}
      {{- end }}
    """
    # Simple conversion: extract role→tag mappings from the template
    # This handles the common Qwen-style templates
    if "<|im_start|>" in template:
        parts = []
        if "system" in template:
            parts.append("<|im_start|>system\n{system}<|im_end|>")
        parts.append("<|im_start|>user\n{user}<|im_end|>")
        parts.append("<|im_start|>assistant")
        return "\n".join(parts)
    return None


def _get_family(model: str) -> str | None:
    """Extract model family from a model name (e.g. 'ollama/qwen3:4b' → 'qwen')."""
    name = model.lower().split("/")[-1].split(":")[0]
    for family in _MODEL_TEMPLATES:
        if name.startswith(family):
            return family
    # Try partial match
    for family in _MODEL_TEMPLATES:
        if family in name:
            return family
    return None

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
        if provider_name == "ollama":
            kwargs["keep_alive"] = "30m"
            # Use raw mode for thinking models so content/tool_calls appear in
            # the right fields instead of getting lost in `thinking`.
            family = _get_family(model)
            if family is not None:
                kwargs["extra_body"] = {"raw": True}
                template = _model_template_cache.get(model)
                if template is None:
                    tmpl_data = await _fetch_ollama_template(model, provider.config.base_url or "")
                    if tmpl_data:
                        fmt = _extract_template_format(tmpl_data)
                        if fmt:
                            template = fmt
                fmt_template = template or _MODEL_TEMPLATES[family]
                # Format messages using the template
                parts, sys_parts, user_parts = [], [], []
                for m in messages:
                    role = m.get("role", "user")
                    content = m.get("content", "")
                    if role == "system":
                        sys_parts.append(content)
                    elif role == "user":
                        user_parts.append(content)
                system_text = "\n".join(sys_parts) if sys_parts else ""
                user_text = "\n".join(user_parts) if user_parts else messages[-1].get("content", "")
                formatted = fmt_template.format(system=system_text, user=user_text)
                kwargs["messages"] = [{"role": "user", "content": formatted}]
                # response_format isn't supported in raw mode with Ollama
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
        # Ensure model is prefixed with provider name for LiteLLM routing
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

        # Pass output dimensions if the provider supports it
        if provider.config.supports_output_dimensions:
            kwargs["dimensions"] = settings.llm.embedding_dimensions

        response = await aembedding(**kwargs)
        embeddings = [item["embedding"] for item in response.data]

        # Validate dimension matches the configured column size
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
