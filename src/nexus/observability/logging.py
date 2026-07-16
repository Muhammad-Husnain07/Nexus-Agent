"""Structured logging with structlog."""

from nexus.config.settings import Settings


def setup_logging(settings: Settings) -> None:
    """Configure structlog based on application settings."""
    _ = settings
