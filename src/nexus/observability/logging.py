"""Structured logging with structlog — JSON or console format."""

from __future__ import annotations

import logging
import sys

import structlog

from nexus.config.settings import Settings


def setup_logging(settings: Settings) -> None:
    """Configure structlog and stdlib logging based on application settings.

    Sets the root logger level from ``settings.observability.log_level``.
    When ``log_format`` is ``"json"``, output is JSON lines (suitable for
    production / log aggregators). Otherwise, coloured console output is used.
    """
    level = getattr(logging, settings.observability.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout, force=True)

    if settings.observability.log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.captureWarnings(True)

    structlog.get_logger("nexus.observability.logging").info(
        "Logging configured",
        log_level=settings.observability.log_level,
        log_format=settings.observability.log_format,
    )
