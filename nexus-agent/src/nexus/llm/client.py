"""LLM client wrapping LiteLLM for completions and embeddings."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


class ContextOverflowError(Exception):
    """Raised when prompt tokens exceed the model's context window."""

import httpx
import litellm
from pydantic import BaseModel, Field

from nexus.llm.format_adapter import PromptAdapter
from nexus.llm.format_adapter.transformers import get_transformer
from nexus.llm.format_detector import cached_detect_format, set_cached_format
from nexus.llm.format_detector.engine import detect_format_sync
from nexus.llm.format_detector.fallback import get_fallback_format
from nexus.llm.format_detector.probe import PROBE_KWARGS, PROBE_MESSAGE
from nexus.llm.provider import ProviderRegistry
from nexus.observability.tracing import get_tracer

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
        stop: list[str] | None = None,
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

        # Dynamic prompt format detection and adaptation
        fmt = provider.config.prompt_format
        if fmt == "auto":
            cached = cached_detect_format(model)
            if cached:
                fmt = cached
            else:
                fmt = get_fallback_format(model)
                if fmt == "raw":
                    import litellm as _litellm  # noqa: PLC0415
                    try:
                        _probe_kw = {**kwargs, "messages": PROBE_MESSAGE, **PROBE_KWARGS}
                        _resp = await _litellm.acompletion(**_probe_kw)
                        _content = (_resp.choices[0].message.content or "").strip() if _resp.choices else ""
                        fmt = detect_format_sync(_content) if _content else "raw"
                    except Exception:
                        fmt = "raw"
                set_cached_format(model, fmt)

        # Adapt system prompts to the detected/configured format
        # Passthrough formats skip adaptation (they handle XML natively)
        if not get_transformer(fmt).is_passthrough:
            adapter = PromptAdapter(format_name=fmt)
            adapted = adapter.adapt(
                system=kwargs["messages"][0]["content"] if kwargs["messages"] and kwargs["messages"][0].get("role") == "system" else None,
                messages=kwargs["messages"],
            )
            if adapted:
                kwargs["messages"] = adapted

        # Ollama-specific: tool capability detection
        if provider_name == "ollama":
            supports_tools = await _ollama_supports_tools(model, provider.config.base_url or "")
            if not supports_tools:
                kwargs["extra_body"] = {"raw": True}
                prompt = _format_raw_prompt(kwargs["messages"])
                kwargs["messages"] = [{"role": "user", "content": prompt}]
                kwargs.pop("response_format", None)

        if tools:
            kwargs["tools"] = tools
        if response_format:
            # Dynamic per-model detection — works with ALL providers, no hardcoded names
            try:
                from litellm import get_supported_openai_params  # noqa: PLC0415
                _params = get_supported_openai_params(model) or []
                if "response_format" in _params:
                    kwargs["response_format"] = response_format
                else:
                    log.info("response_format.unsupported model=%s", model)
            except Exception:
                if provider.config.supports_structured_output:
                    kwargs["response_format"] = response_format
        temp = temperature
        if temp is None:
            temp = getattr(provider.config, "temperature", _LITELLM_TEMPERATURE)
        kwargs["temperature"] = temp
        kwargs["max_tokens"] = max_tokens if max_tokens is not None else provider.config.max_tokens
        if stop is not None:
            kwargs["stop"] = stop

        # Quick estimate: skip expensive context management for small prompts
        prompt_text = " ".join(m.get("content", "") or "" for m in kwargs.get("messages", []))
        small_prompt = len(prompt_text) < 4000
        if not small_prompt:
            try:
                from litellm.utils import trim_messages  # noqa: PLC0415
                trimmed = trim_messages(kwargs.get("messages", []), model=model, trim_ratio=0.75)
                if trimmed:
                    kwargs["messages"] = trimmed
            except Exception:
                pass
            try:
                capped, pt = await self._enforce_context_window(kwargs, provider)
                log.info("context_window.enforced prompt_tokens=%s max_tokens=%s context_window=%s", pt, capped, self._get_context_window(model, provider))
            except ContextOverflowError:
                raise

        if stream:
            return self._stream_complete(kwargs, model, provider_name)
        try:
            return await self._complete(kwargs, model, provider_name, start)
        except litellm.ContextWindowExceededError:
            # Retry once with trimmed messages
            msgs = kwargs.get("messages", [])
            if len(msgs) > 2:
                trim = max(1, len(msgs) // 4)
                kwargs["messages"] = msgs[:1] + msgs[trim + 1:]
                log.warning("context_window.retry_trimmed trimmed=%s original=%s", trim, len(msgs))
                return await self._complete(kwargs, model, provider_name, start)
            raise

    async def _complete(
        self,
        kwargs: dict[str, Any],
        model: str,
        provider_name: str,
        start: float,
    ) -> LLMResponse:
        tracer = get_tracer()
        with tracer.start_as_current_span("llm.complete") as span:
            span.set_attribute("llm.model", model)
            span.set_attribute("llm.provider", provider_name)
            span.set_attribute("llm.temperature", str(kwargs.get("temperature", "")))
            response = await litellm.acompletion(**kwargs)
            latency_ms = (time.monotonic() - start) * 1000
            usage = response.usage if hasattr(response, "usage") else None
            if usage:
                pt = usage.prompt_tokens or 0
                ct = usage.completion_tokens or 0
                span.set_attribute("llm.token.prompt", pt)
                span.set_attribute("llm.token.completion", ct)
                span.set_attribute("llm.token.total", pt + ct)
            span.set_attribute("llm.latency_ms", latency_ms)
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

    @staticmethod
    def _get_context_window(model: str, provider: Any) -> int:
        """Look up model context window from LiteLLM registry, with fallback.

        Uses litellm.model_cost (300+ models, community-maintained) to find
        the model's max_input_tokens. Falls back to provider config if the
        model is not in the registry. No hardcoded model names.
        """
        from litellm import model_cost  # noqa: PLC0415
        # Try exact match, then suffix match (strip provider prefix)
        model_key = model.split("/", 1)[-1] if "/" in model else model
        entry = model_cost.get(model, {}) or model_cost.get(model_key, {})
        ctx = entry.get("max_input_tokens") if entry else None
        if ctx is None:
            ctx = provider.config.max_input_tokens
        return ctx

    @staticmethod
    async def _count_prompt_tokens(model: str, messages: list[dict[str, Any]]) -> int:
        """Count tokens in the prompt using LiteLLM's provider-aware counter.

        Falls back to tiktoken if the provider doesn't support token counting.
        """
        try:
            from litellm import acount_tokens  # noqa: PLC0415
            count = await acount_tokens(model=model, messages=messages)
            return count.total_tokens or 0
        except Exception:
            # Fallback: tiktoken or rough estimate
            text = " ".join(m.get("content", "") or "" for m in messages)
            return len(text) // 4 or 1

    async def _enforce_context_window(
        self,
        kwargs: dict[str, Any],
        provider: Any,
    ) -> tuple[int, int]:
        """Dynamically enforce context window limits.

        Returns (capped_max_tokens, prompt_tokens) for logging.
        Raises ContextOverflowError if prompt exceeds the window.
        """
        messages = kwargs.get("messages", [])
        model = kwargs.get("model", "")
        requested_max = kwargs.get("max_tokens")

        ctx = self._get_context_window(model, provider)
        prompt_tokens = await self._count_prompt_tokens(model, messages)

        if prompt_tokens > ctx:
            raise ContextOverflowError(
                f"Prompt has {prompt_tokens} tokens but {model}'s context "
                f"window is {ctx}. Start a new session or reduce history."
            )

        # Reserve 20% of remaining for output — prevents "requested X but only Y free" errors
        remaining = ctx - prompt_tokens
        output_budget = int(remaining * 0.8) if remaining > 0 else 0

        if requested_max is None or requested_max > output_budget:
            kwargs["max_tokens"] = max(1, output_budget)

        return kwargs["max_tokens"], prompt_tokens

    @staticmethod
    def _sanitize_output(text: str) -> str:
        """Strip common LLM artifacts from response text.

        Patterns stripped (trailing only to avoid damaging legitimate content):
        - ### and any sequence of # characters
        - Qwen/chat template tokens: <|im_end|>, <|endoftext|>
        - Unclosed XML structural tags at the end
        - Trailing whitespace/newlines
        """
        # Strip trailing whitespace first
        text = text.rstrip()
        # Strip trailing ## delimiters (common in Qwen output)
        text = re.sub(r"\n?#+\s*$", "", text)
        # Strip trailing chat template tokens
        text = re.sub(r"<\|im_end\|>\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<\|endoftext\|>\s*$", "", text, flags=re.IGNORECASE)
        # Strip trailing XML structural tags that are clearly artifacts
        text = re.sub(
            r"</?(role|context|instructions|thinking|output|output_format|"
            r"thinking_protocol|rules|rule|criterion|step_details|"
            r"decision_rules|available_tools|examples|common_mistakes|"
            r"missing_information|slot_details|reflection_context|"
            r"tool_results|errors|when_to_split|when_not_to_split|"
            r"memories|improvement_feedback|example|mistake|wrong_output|"
            r"correction|input|right|explanation|scenario)>"
            r"\s*$",
            "", text, flags=re.IGNORECASE,
        )
        # Final trim
        return text.strip()

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

        raw_text = getattr(content, "content", None) if content else None
        sanitized = self._sanitize_output(raw_text) if raw_text else None

        return LLMResponse(
            content=sanitized,
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
