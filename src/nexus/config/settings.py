"""Application settings via Pydantic BaseSettings with nested groups."""

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    """PostgreSQL connection and pool configuration.

    Fields:
        url: PostgreSQL async connection string (asyncpg driver).
        pool_size: Number of connections to maintain in the pool.
        max_overflow: Maximum overflow connections beyond pool_size.
        echo_sql: Log all SQL statements.
        statement_timeout_ms: Maximum execution time per statement in ms.
    """

    url: str = Field(
        default="postgresql+asyncpg://nexus:nexus@localhost:5432/nexus",
        description="PostgreSQL async connection string",
    )
    pool_size: int = Field(default=10, ge=1, description="Connection pool size")
    max_overflow: int = Field(default=20, ge=0, description="Max overflow connections")
    echo_sql: bool = Field(default=False, description="Log SQL statements")
    statement_timeout_ms: int = Field(
        default=30000, ge=0, description="Statement timeout in milliseconds"
    )


class RedisSettings(BaseModel):
    """Redis cache and pub/sub connection configuration.

    Fields:
        url: Redis connection string.
        db: Redis database index.
        max_connections: Maximum connections in the pool.
        ssl: Enable SSL for Redis connection.
    """

    url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string",
    )
    db: int = Field(default=0, ge=0, description="Redis database index")
    max_connections: int = Field(default=20, ge=1, description="Max pool connections")
    ssl: bool = Field(default=False, description="Enable SSL for Redis")


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider.

    Fields:
        name: Provider identifier (e.g. openai, anthropic).
        base_url: Custom API base URL if different from default.
        api_key_env: Environment variable name holding the API key.
        models: List of model identifiers available from this provider.
        cost_per_1k_input: Cost per 1,000 input tokens in USD.
        cost_per_1k_output: Cost per 1,000 output tokens in USD.
    """

    name: str = Field(description="Provider identifier")
    base_url: str = Field(default="", description="Custom API base URL")
    api_key_env: str = Field(default="", description="Env var name for API key")
    models: list[str] = Field(default_factory=list, description="Available model IDs")
    cost_per_1k_input: float = Field(default=0.0, ge=0, description="Input cost per 1K tokens")
    cost_per_1k_output: float = Field(default=0.0, ge=0, description="Output cost per 1K tokens")


class LLMSettings(BaseModel):
    """LLM provider and model defaults.

    Fields:
        default_provider: Default LLM provider name.
        default_model: Default model identifier.
        temperature: Sampling temperature (0.0 to 2.0).
        max_tokens: Maximum tokens per response.
        timeout_s: Request timeout in seconds.
        max_retries: Max retries on failure.
        providers: List of configured provider definitions.
    """

    default_provider: str = Field(default="openai", description="Default LLM provider")
    default_model: str = Field(default="gpt-4o", description="Default model identifier")
    temperature: float = Field(default=0.7, ge=0, le=2, description="Sampling temperature")
    max_tokens: int = Field(default=4096, ge=1, description="Max tokens per response")
    timeout_s: int = Field(default=60, ge=1, description="Request timeout in seconds")
    max_retries: int = Field(default=3, ge=0, description="Max retries on failure")
    providers: list[ProviderConfig] = Field(
        default_factory=list, description="Configured LLM providers"
    )


class AuthSettings(BaseModel):
    """Authentication and authorization configuration.

    Fields:
        jwt_secret: Secret key for JWT signing.
        jwt_algorithm: JWT signing algorithm.
        access_token_ttl_minutes: Access token lifetime in minutes.
        refresh_token_ttl_days: Refresh token lifetime in days.
        api_key_header_name: HTTP header name for API key authentication.
    """

    jwt_secret: SecretStr = Field(
        default=SecretStr("dev-secret-change-in-production"),
        description="JWT signing secret",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    access_token_ttl_minutes: int = Field(
        default=30, ge=1, description="Access token TTL in minutes"
    )
    refresh_token_ttl_days: int = Field(default=7, ge=1, description="Refresh token TTL in days")
    api_key_header_name: str = Field(default="X-API-Key", description="API key header name")


class ObservabilitySettings(BaseModel):
    """Observability, tracing, and logging configuration.

    Fields:
        langsmith_api_key: LangSmith API key for tracing.
        langsmith_project: LangSmith project name.
        otel_endpoint: OpenTelemetry collector endpoint.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR).
        log_format: Output format — json or console.
    """

    langsmith_api_key: SecretStr | None = Field(default=None, description="LangSmith API key")
    langsmith_project: str = Field(default="nexus-agent", description="LangSmith project name")
    otel_endpoint: str | None = Field(default=None, description="OpenTelemetry collector endpoint")
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: Literal["json", "console"] = Field(
        default="console", description="Log output format"
    )


class AgentSettings(BaseModel):
    """LangGraph agent execution configuration.

    Fields:
        max_iterations: Maximum agent iterations per conversation turn.
        max_plan_steps: Maximum planning steps before execution.
        context_window_tokens: Maximum context window in tokens.
        summarization_threshold_tokens: Token count triggering summarization.
        hitl_default: Require human approval for tool calls by default.
        hitl_tool_patterns: Regex patterns for tools requiring HITL approval.
    """

    max_iterations: int = Field(default=25, ge=1, description="Max iterations per turn")
    max_plan_steps: int = Field(default=10, ge=1, description="Max planning steps")
    context_window_tokens: int = Field(default=128000, ge=1, description="Context window in tokens")
    summarization_threshold_tokens: int = Field(
        default=64000, ge=1, description="Summarization threshold in tokens"
    )
    hitl_default: bool = Field(default=True, description="Require HITL approval by default")
    hitl_tool_patterns: list[str] = Field(
        default_factory=list,
        description="Regex patterns for HITL-required tools",
    )


class ToolSettings(BaseModel):
    """Tool execution and sandbox configuration.

    Fields:
        execution_timeout_s: Max execution time per tool call in seconds.
        max_retries: Max retries per tool call.
        retry_backoff_s: Base backoff in seconds between retries.
        sandbox_enabled: Enable sandboxed tool execution.
        allowed_hosts: List of allowed external hosts for tool HTTP calls.
    """

    execution_timeout_s: int = Field(default=30, ge=1, description="Tool execution timeout")
    max_retries: int = Field(default=3, ge=0, description="Max tool retries")
    retry_backoff_s: float = Field(default=1.0, ge=0, description="Retry backoff seconds")
    sandbox_enabled: bool = Field(default=False, description="Enable sandboxed execution")
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["*"], description="Allowed external hosts"
    )


class ServerSettings(BaseModel):
    """FastAPI server configuration.

    Fields:
        host: Bind address for the HTTP server.
        port: Listen port.
        workers: Number of worker processes.
        cors_origins: Allowed CORS origins.
        docs_url: Path for OpenAPI docs (set to None to disable).
    """

    host: str = Field(default="0.0.0.0", description="Server bind address")  # noqa: S104
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")
    workers: int = Field(default=1, ge=1, description="Number of workers")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"], description="Allowed CORS origins"
    )
    docs_url: str = Field(default="/docs", description="OpenAPI docs path")


class Settings(BaseSettings):
    """Root application configuration.

    All nested groups are loaded from environment variables with the
    NEXUS_ prefix and __ delimiter (e.g. NEXUS_DATABASE__URL).
    """

    model_config = SettingsConfigDict(
        env_prefix="NEXUS_",
        env_nested_delimiter="__",
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database: DatabaseSettings = Field(
        default_factory=DatabaseSettings, description="Database configuration"
    )
    redis: RedisSettings = Field(default_factory=RedisSettings, description="Redis configuration")
    llm: LLMSettings = Field(default_factory=LLMSettings, description="LLM configuration")
    auth: AuthSettings = Field(description="Authentication configuration")
    observability: ObservabilitySettings = Field(
        default_factory=ObservabilitySettings, description="Observability configuration"
    )
    agent: AgentSettings = Field(
        default_factory=AgentSettings, description="Agent orchestration configuration"
    )
    tools: ToolSettings = Field(
        default_factory=ToolSettings, description="Tool execution configuration"
    )
    server: ServerSettings = Field(
        default_factory=ServerSettings, description="Server configuration"
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
