"""OpenTelemetry and LangSmith tracing setup with LiteLLM callback wiring."""

from __future__ import annotations

import logging
import os

from nexus.config.settings import Settings

logger = logging.getLogger("nexus.observability.tracing")


def setup_tracing(settings: Settings) -> None:
    """Configure LangSmith and/or OpenTelemetry tracing, wired to LiteLLM callbacks.

    LangSmith is enabled when ``settings.observability.langsmith_api_key`` is set.
    OpenTelemetry is enabled when ``settings.observability.otel_endpoint`` is set.
    """
    _setup_langsmith(settings)
    _setup_opentelemetry(settings)


def _setup_langsmith(settings: Settings) -> None:
    api_key = settings.observability.langsmith_api_key
    if not api_key or not api_key.get_secret_value():
        return
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", api_key.get_secret_value())
    os.environ.setdefault("LANGSMITH_PROJECT", settings.observability.langsmith_project)
    os.environ.setdefault("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

    import litellm  # noqa: PLC0415

    litellm.success_callback = ["langsmith"]
    logger.info(
        "LangSmith tracing enabled for LiteLLM",
        extra={"project": settings.observability.langsmith_project},
    )


def _setup_opentelemetry(settings: Settings) -> None:
    endpoint = settings.observability.otel_endpoint
    if not endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: PLC0415

    provider = TracerProvider()
    exporter = OTLPSpanExporter(endpoint=endpoint)
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)
    from opentelemetry import trace  # noqa: PLC0415

    trace.set_tracer_provider(provider)

    _setup_auto_instrumentation()

    import litellm  # noqa: PLC0415
    from litellm.integrations.custom_logger import CustomLogger  # noqa: PLC0415

    class OTelLiteLLMLogger(CustomLogger):  # type: ignore[misc]
        """LiteLLM callback that creates OpenTelemetry spans for LLM calls."""

        def __init__(self) -> None:
            self._tracer = trace.get_tracer("nexus.llm")

        def log_success_event(  # type: ignore[override]
            self,
            kwargs: dict,
            response_obj: object,
            start_time: float,
            end_time: float,
        ) -> None:
            with self._tracer.start_as_current_span("llm.completion") as span:
                span.set_attribute("llm.model", kwargs.get("model", ""))
                span.set_attribute("llm.provider", kwargs.get("custom_llm_provider", ""))
                span.set_attribute("llm.latency_ms", (end_time - start_time) * 1000)

        def log_failure_event(  # type: ignore[override]
            self,
            kwargs: dict,
            response_obj: object,
            start_time: float,
            end_time: float,
        ) -> None:
            with self._tracer.start_as_current_span("llm.completion.error") as span:
                span.set_attribute("llm.model", kwargs.get("model", ""))
                span.set_attribute("llm.error", str(kwargs.get("exception", "")))
                span.set_attribute("llm.latency_ms", (end_time - start_time) * 1000)

    litellm.callbacks = [OTelLiteLLMLogger()]
    logger.info(
        "OpenTelemetry tracing enabled for LiteLLM",
        extra={"endpoint": endpoint},
    )


def _setup_auto_instrumentation() -> None:
    """Auto-instrument httpx, asyncpg, redis, and fastapi for OpenTelemetry."""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        pass

    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

        AsyncPGInstrumentor().instrument()
    except ImportError:
        pass

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
    except ImportError:
        pass

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        pass
