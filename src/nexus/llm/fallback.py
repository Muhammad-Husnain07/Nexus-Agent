"""Fallback chain for LLM calls — try primary, cascade to fallbacks on failure."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from nexus.llm.client import LLMChunk, LLMClient, LLMResponse
from nexus.llm.retries import is_non_retryable, llm_retry_policy

logger = logging.getLogger("nexus.llm.fallback")


class AllProvidersFailedError(Exception):
    """Raised when all providers in the fallback chain have been exhausted."""

    def __init__(self, model: str, attempts: int, total_cost_usd: float) -> None:
        self.model = model
        self.attempts = attempts
        self.total_cost_usd = total_cost_usd
        super().__init__(
            f"All providers exhausted for model chain starting with '{model}' "
            f"after {attempts} attempt(s), cost=${total_cost_usd:.6f}"
        )


class FallbackChain:
    """Execute an LLM call with automatic fallback to secondary models.

    Tries the primary model first with retry. If all retries are exhausted,
    logs the failure and tries the next fallback model. Aggregates total cost
    across all attempts.

    Attributes:
        client: LLMClient instance for making calls.
        max_attempts_per_model: Number of retries per model before falling back.
    """

    def __init__(
        self,
        client: LLMClient,
        max_attempts_per_model: int = 3,
    ) -> None:
        self._client = client
        self._max_attempts_per_model = max_attempts_per_model
        self._total_cost_usd: float = 0.0

    async def execute(  # noqa: PLR0913
        self,
        primary: str,
        fallbacks: list[str],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> LLMResponse | AsyncIterator[LLMChunk]:
        """Execute a completion with fallback support.

        Args:
            primary: Primary model identifier.
            fallbacks: Ordered list of fallback model identifiers.
            messages: Conversation messages.
            tools: Optional tool definitions.
            response_format: Optional structured output format.
            temperature: Sampling temperature override.
            max_tokens: Max tokens override.
            stream: If True, return streaming iterator (no fallback on partial stream).

        Returns:
            LLMResponse for non-streaming, or AsyncIterator[LLMChunk] for streaming.

        Raises:
            AllProvidersFailedError: If all models in the chain are exhausted.
        """
        if stream:
            return await self._execute_stream(primary, messages, tools, temperature, max_tokens)

        return await self._execute_non_stream(
            primary, fallbacks, messages, tools, response_format, temperature, max_tokens
        )

    async def _execute_non_stream(  # noqa: PLR0913
        self,
        primary: str,
        fallbacks: list[str],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> LLMResponse:
        models_to_try = [primary] + fallbacks
        last_error: Exception | None = None

        for model in models_to_try:
            try:
                retry_policy = llm_retry_policy(max_attempts=self._max_attempts_per_model)
                async for attempt in retry_policy:
                    with attempt:
                        response = await self._client.complete(
                            model=model,
                            messages=messages,
                            tools=tools,
                            response_format=response_format,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            stream=False,
                        )
                        if isinstance(response, LLMResponse):
                            self._total_cost_usd += response.cost_usd
                            return response
            except Exception as exc:
                if is_non_retryable(exc):
                    raise
                last_error = exc
                logger.warning(
                    "Fallback triggered: model=%s failed, trying next",
                    model,
                    exc_info=exc,
                )
                if hasattr(exc, "cost_usd"):
                    self._total_cost_usd += getattr(exc, "cost_usd", 0.0)

        raise AllProvidersFailedError(
            model=primary,
            attempts=len(models_to_try) * self._max_attempts_per_model,
            total_cost_usd=self._total_cost_usd,
        ) from last_error

    async def _execute_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> AsyncIterator[LLMChunk]:
        result = await self._client.complete(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        if isinstance(result, AsyncIterator):
            return result
        raise TypeError("Expected AsyncIterator for streaming response")

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd
