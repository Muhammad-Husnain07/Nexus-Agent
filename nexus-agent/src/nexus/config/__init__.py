"""Application configuration via Pydantic BaseSettings."""

from nexus.config.secrets import (
    EnvSecretResolver,
    SecretResolver,
    VaultSecretResolver,
)
from nexus.config.settings import (
    AgentSettings,
    DatabaseSettings,
    LLMSettings,
    ObservabilitySettings,
    ProviderConfig,
    RedisSettings,
    ServerSettings,
    Settings,
    ToolSettings,
    get_settings,
)

__all__ = [
    "AgentSettings",
    "DatabaseSettings",
    "EnvSecretResolver",
    "LLMSettings",
    "ObservabilitySettings",
    "ProviderConfig",
    "RedisSettings",
    "SecretResolver",
    "ServerSettings",
    "Settings",
    "ToolSettings",
    "VaultSecretResolver",
    "get_settings",
]
