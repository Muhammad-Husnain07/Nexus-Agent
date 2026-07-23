"""OpenTelemetry tracing setup with batch span export.

Configures a global TracerProvider with an OTLP HTTP exporter.
Adds trace context to structlog for log-trace correlation.
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.observability.tracing")

_TRACER: Any = None  # Avoid import overhead when tracing is disabled


def get_tracer() -> Any:
    """Return the global tracer or a no-op tracer if tracing is disabled."""
    global _TRACER  # noqa: PLW0603
    if _TRACER is not None:
        return _TRACER
    try:
        from opentelemetry import trace  # noqa: PLC0415
        _TRACER = trace.get_tracer("nexus-agent", "0.1.0")
    except Exception:
        _TRACER = _NoOpTracer()
    return _TRACER


def setup_tracing() -> None:
    """Initialize OpenTelemetry tracing from settings.

    Called once during application startup (lifespan).
    If no OTLP endpoint is configured, tracing is a no-op.
    """
    settings = get_settings().observability
    if not settings.otel_endpoint:
        logger.info("tracing.disabled", reason="no otel_endpoint configured")
        return

    try:
        from opentelemetry import trace  # noqa: PLC0415
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
        from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
        from opentelemetry.sdk.trace.export import (  # noqa: PLC0415
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )

        resource = Resource.create({"service.name": "nexus-agent"})
        provider = TracerProvider(resource=resource)

        # OTLP exporter to configured endpoint
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

        # Also log spans to console in debug mode
        if get_settings().observability.log_level == "DEBUG":
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        trace.set_tracer_provider(provider)
        logger.info("tracing.initialized", endpoint=settings.otel_endpoint)
    except Exception as exc:
        logger.warning("tracing.init_failed", error=str(exc))


def add_trace_context_to_structlog() -> None:
    """Add trace_id and span_id to structlog context.

    Must be called after structlog is configured.  Adds a processor
    that injects the current OpenTelemetry trace context into each
    log entry.
    """
    try:
        from opentelemetry import trace  # noqa: PLC0415

        def _add_trace_context(logger: Any, method_name: str, event_dict: Any) -> Any:  # noqa: ARG001
            span = trace.get_current_span()
            span_context = span.get_span_context()
            if span_context.is_valid:
                event_dict["trace_id"] = hex(span_context.trace_id)
                event_dict["span_id"] = hex(span_context.span_id)
            return event_dict

        structlog.configure(processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            _add_trace_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer() if get_settings().observability.log_format == "console"
            else structlog.processors.JSONRenderer(),
        ])
        logger.info("tracing.structlog_context_enabled")
    except Exception:
        pass


class _NoOpTracer:
    """Fallback tracer that does nothing — avoids None checks everywhere."""

    def start_as_current_span(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        return _NoOpSpan()

    def start_span(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        return _NoOpSpan()


class _NoOpSpan:
    """Context manager that does nothing."""

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def set_attribute(self, *args: Any, **kwargs: Any) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def end(self) -> None:
        pass

    def get_span_context(self) -> Any:
        return _NoOpSpanContext()


class _NoOpSpanContext:
    is_valid: bool = False
    trace_id: int = 0
    span_id: int = 0
