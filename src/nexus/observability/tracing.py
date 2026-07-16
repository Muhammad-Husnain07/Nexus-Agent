"""OpenTelemetry tracing setup."""

from nexus.config.settings import Settings


def setup_tracing(settings: Settings) -> None:
    """Configure OpenTelemetry tracing based on application settings."""
    _ = settings
