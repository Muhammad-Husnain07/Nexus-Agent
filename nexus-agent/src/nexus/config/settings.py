"""Application settings via Pydantic BaseSettings with nested groups."""

from functools import lru_cache
from typing import Any, Literal, get_args

# Supported prompt format identifiers — fully dynamic, no hardcoded model mappings
_PROMPT_FORMATS = Literal["auto", "anthropic", "openai", "gemini", "deepseek", "llama", "qwen", "mistral", "raw"]
PROMPT_FORMAT_VALUES: tuple[str, ...] = get_args(_PROMPT_FORMATS)
PROMPT_FORMATS: tuple[str, ...] = PROMPT_FORMAT_VALUES  # public alias

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
        api_key_ref: Environment variable name or secret ref for the API key.
        models: List of model identifiers available from this provider.
        cost_per_1k_input: Cost per 1,000 input tokens in USD.
        cost_per_1k_output: Cost per 1,000 output tokens in USD.
        max_tokens: Default max tokens for responses from this provider.
        supports_streaming: Whether the provider supports streaming responses.
        supports_tools: Whether the provider supports tool/function calling.
        supports_structured_output: Whether the provider supports JSON structured output.
        default_headers: Optional default HTTP headers for API requests.
    """

    name: str = Field(description="Provider identifier")
    base_url: str = Field(default="", description="Custom API base URL")
    api_key_ref: str = Field(default="", description="Env var or secret ref for API key")
    models: list[str] = Field(default_factory=list, description="Available model IDs")
    cost_per_1k_input: float = Field(default=0.0, ge=0, description="Input cost per 1K tokens")
    cost_per_1k_output: float = Field(default=0.0, ge=0, description="Output cost per 1K tokens")
    max_tokens: int = Field(default=4096, ge=1, description="Default max tokens for responses")
    max_input_tokens: int = Field(default=128000, ge=1, description="Max input context window (fallback if model not in LiteLLM registry)")
    supports_streaming: bool = Field(default=True, description="Supports streaming responses")
    supports_tools: bool = Field(default=True, description="Supports tool/function calling")
    supports_structured_output: bool = Field(
        default=False, description="Supports JSON structured output"
    )
    supports_output_dimensions: bool = Field(
        default=False, description="Supports setting output vector dimensions (OpenAI text-embedding-3-*)"
    )
    default_headers: dict[str, str] = Field(
        default_factory=dict, description="Default HTTP headers for API requests"
    )
    extra_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra kwargs passed to the provider (e.g. {\"options\": {\"think\": false}} for Qwen)",
    )
    prompt_format: str = Field(
        default="auto",
        description="Prompt format for this provider. 'auto' = runtime probe detect. Options: " + ", ".join(PROMPT_FORMAT_VALUES),
    )


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
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Default embedding model"
    )
    embedding_dimensions: int = Field(
        default=768, ge=1, description="Output dimensions for the embedding column (must match DB VECTOR(n))"
    )
    timeout_s: int = Field(default=60, ge=1, description="Request timeout in seconds")
    max_retries: int = Field(default=3, ge=0, description="Max retries on failure")
    providers: list[ProviderConfig] = Field(
        default_factory=list, description="Configured LLM providers"
    )





class ExperimentSettings(BaseModel):
    """Configuration for A/B experiments and prompt version testing.

    Fields:
        ab_test_enabled: Master switch for A/B experiment assignments.
        experiment_id: Current experiment identifier for outcome tracking.
        variant_weights: Per-prompt-name mapping of version → probability weights.
    """

    ab_test_enabled: bool = Field(default=False, description="Enable A/B experiment tracking")
    experiment_id: str | None = Field(default=None, description="Current experiment ID")
    variant_weights: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Prompt name → {version: weight} for A/B assignment",
    )


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


class MemorySettings(BaseModel):
    """Long-term memory, working memory, and consolidation configuration.

    Fields:
        enabled: Enable memory extraction and retrieval.
        retrieval_top_k: Number of memories to retrieve per query.
        importance_threshold: Minimum importance score for memories to retain.
        similarity_threshold: Cosine similarity threshold for deduplication (0-1).
        checkpointer_type: Checkpointer backend — postgres or memory.
        working_memory_max_entries: Max working memory entries before eviction.
        working_memory_inject_count: Number of recent entries to inject into prompts.
        scout_enabled: Enable proactive memory retrieval at multiple trigger points.
        scout_max_injection_tokens: Max tokens per memory injection.
        scout_mmr_lambda: MMR diversity weight (0=all diverse, 1=all relevant).
        consolidation_interval_minutes: Minutes between consolidation runs.
        consolidation_cluster_eps: DBSCAN epsilon for memory clustering.
        consolidation_min_cluster: Minimum cluster size for consolidation.
        decay_base_rate: Base decay rate for adaptive memory decay.
        decay_importance_floor: Minimum importance before potential archival.
        decay_archive_threshold: Importance below which memories are archived.
    """

    enabled: bool = Field(default=True, description="Enable memory extraction and retrieval")
    retrieval_top_k: int = Field(default=5, ge=1, le=50, description="Memories per query")
    importance_threshold: float = Field(
        default=0.3, ge=0, le=1, description="Minimum importance to retain"
    )
    similarity_threshold: float = Field(
        default=0.92, ge=0, le=1, description="Cosine similarity for dedup"
    )
    checkpointer_type: str = Field(
        default="postgres", description="Checkpointer backend: postgres or memory"
    )

    # Working memory
    working_memory_max_entries: int = Field(
        default=50, ge=10, le=500, description="Max working memory entries"
    )
    working_memory_inject_count: int = Field(
        default=10, ge=1, le=50, description="Recent entries to inject into prompts"
    )

    # Proactive scout
    scout_enabled: bool = Field(default=True, description="Enable proactive memory retrieval")
    scout_max_injection_tokens: int = Field(
        default=800, ge=0, le=8000, description="Max tokens per memory injection"
    )
    scout_mmr_lambda: float = Field(
        default=0.7, ge=0, le=1, description="MMR diversity-relevance tradeoff"
    )

    # Consolidation
    consolidation_interval_minutes: int = Field(
        default=30, ge=5, le=1440, description="Minutes between consolidation runs"
    )
    consolidation_cluster_eps: float = Field(
        default=0.3, ge=0.05, le=1.0, description="DBSCAN epsilon for clustering"
    )
    consolidation_min_cluster: int = Field(
        default=2, ge=2, le=20, description="Minimum cluster size for merge"
    )

    # Decay
    decay_base_rate: float = Field(
        default=0.05, ge=0.001, le=1.0, description="Base adaptive decay rate"
    )
    decay_importance_floor: float = Field(
        default=0.1, ge=0, le=1, description="Minimum importance before archival"
    )
    decay_archive_threshold: float = Field(
        default=0.05, ge=0, le=1, description="Archive memories below this importance"
    )


class AdaptiveReflectionSettings(BaseModel):
    """Adaptive reflection, self-consistency, and uncertainty-aware routing config.

    Fields:
        base_threshold: Base acceptance threshold for reflection score (0-1).
        domain_thresholds: Per-response-type threshold overrides.
        convergence_delta: Minimum score improvement to continue refining.
        convergence_window: Number of consecutive rounds with <delta improvement to stop.
        max_escalation_rounds: Rounds before attempting model escalation.
        self_consistency_k: Number of parallel samples for moderate confidence.
        self_consistency_early_stop: Stop sampling if first k-1 agree.
        max_concurrent_tasks: Default max parallel tool executions.
        cost_budget_usd: Max API cost per task before accepting best-so-far.
        confidence_high: Threshold for direct proceed (>= this).
        confidence_moderate: Threshold for self-consistency band.
        confidence_low: Threshold for clarification (< this).
    """

    base_threshold: float = Field(default=0.7, ge=0, le=1, description="Base acceptance score threshold")
    domain_thresholds: dict[str, float] = Field(
        default_factory=lambda: {"tool": 0.8, "greeting": 0.5, "meta": 0.6, "memory_query": 0.7},
        description="Per-response-type threshold overrides",
    )
    convergence_delta: float = Field(default=0.02, ge=0, le=1, description="Min score delta to continue")
    convergence_window: int = Field(default=2, ge=1, description="Rounds of low delta to stop")
    max_escalation_rounds: int = Field(default=2, ge=0, description="Rounds before model escalation")
    self_consistency_k: int = Field(default=3, ge=1, le=10, description="Parallel samples for uncertainty")
    self_consistency_early_stop: bool = Field(default=True, description="Stop early if samples agree")
    max_concurrent_tasks: int = Field(default=5, ge=1, le=50, description="Max parallel tool calls")
    cost_budget_usd: float = Field(default=0.50, ge=0, description="Max API cost per task")
    max_speculative_approaches: int = Field(default=3, ge=1, le=10, description="Max parallel speculative branches per task")
    speculative_timeout_s: float = Field(default=15.0, ge=1, description="Timeout per speculative branch")
    max_dag_generations: int = Field(default=3, ge=1, le=10, description="Max recursive DAG expansion depth")
    confidence_high: float = Field(default=0.9, ge=0, le=1, description="Proceed directly threshold")
    confidence_moderate: float = Field(default=0.7, ge=0, le=1, description="Self-consistency band start")
    confidence_low: float = Field(default=0.5, ge=0, le=1, description="Clarification threshold")


class AgentSettings(BaseModel):
    """LangGraph agent execution configuration.

    Fields:
        max_iterations: Maximum agent iterations per conversation turn.
        context_window_tokens: Maximum context window in tokens.
        summarization_threshold_tokens: Token count triggering summarization.
        adaptive_reflection: Adaptive reflection and uncertainty settings.
    """

    max_iterations: int = Field(default=25, ge=1, description="Max iterations per turn")
    context_window_tokens: int = Field(default=128000, ge=1, description="Context window in tokens")
    summarization_threshold_tokens: int = Field(
        default=64000, ge=1, description="Summarization threshold in tokens"
    )
    run_lock_ttl_s: int = Field(
        default=600,
        ge=30,
        le=3600,
        description="TTL in seconds for the per-session run lock (heartbeat renews every ttl/3)",
    )
    adaptive_reflection: AdaptiveReflectionSettings = Field(
        default_factory=AdaptiveReflectionSettings,
        description="Adaptive reflection and uncertainty settings",
    )


class ToolSettings(BaseModel):
    """Tool execution, performance, and error recovery configuration.

    Fields:
        execution_timeout_s: Max execution time per tool call in seconds.
        max_retries: Max retries per tool call.
        retry_backoff_s: Base backoff in seconds between retries.
        sandbox_enabled: Enable sandboxed tool execution.
        allowed_hosts: List of allowed external hosts for tool HTTP calls.
        performance_weight: Weight of performance vs relevance in tool ranking (0-1).
        performance_window_minutes: Sliding window for performance metrics.
        degradation_error_rate: Error rate threshold for degradation detection.
        degradation_latency_multiplier: Latency multiplier threshold for degradation.
        degradation_min_samples: Minimum samples before degradation check.
        degradation_cooldown_minutes: Cooldown before auto-recovery.
    """

    execution_timeout_s: int = Field(default=30, ge=1, description="Tool execution timeout")
    max_retries: int = Field(default=3, ge=0, description="Max tool retries")
    retry_backoff_s: float = Field(default=1.0, ge=0, description="Retry backoff seconds")
    sandbox_enabled: bool = Field(default=True, description="Enable sandboxed execution")
    allowed_hosts: list[str] = Field(
        default_factory=list, description="Allowed external hosts (empty = block all)"
    )
    proxy_url: str | None = Field(
        default=None, description="HTTP proxy URL for tool calls (e.g. http://proxy:8080)"
    )
    http2_enabled: bool = Field(default=True, description="Enable HTTP/2 for tool calls")

    # Performance-aware selection
    performance_weight: float = Field(default=0.4, ge=0, le=1, description="Performance vs relevance weight")
    performance_window_minutes: int = Field(default=60, ge=1, description="Sliding window for metrics")

    # Degradation detection
    degradation_error_rate: float = Field(default=0.3, ge=0, le=1, description="Error rate threshold for degradation")
    degradation_latency_multiplier: float = Field(default=3.0, ge=1, description="Latency multiplier threshold")
    degradation_min_samples: int = Field(default=5, ge=1, description="Min samples before degradation check")
    degradation_cooldown_minutes: int = Field(default=15, ge=1, description="Cooldown before auto-recovery")

    # JSON extraction pipeline for LLM outputs (dynamic, model-agnostic)
    # Ordered list of strategy names to try. Options: output_tags, brace_counting, json5
    json_extraction_pipeline: list[str] = Field(
        default=["output_tags", "brace_counting", "json5"],
        description="JSON extraction strategy pipeline (order matters)",
    )
    # Tags to strip from LLM output before JSON extraction falls back to preprocess
    json_extraction_strip_tags: list[str] = Field(
        default=["thinking", "think", "output"],
        description="XML/HTML tags to strip before JSON extraction",
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
    observability: ObservabilitySettings = Field(
        default_factory=ObservabilitySettings, description="Observability configuration"
    )
    agent: AgentSettings = Field(
        default_factory=AgentSettings, description="Agent orchestration configuration"
    )
    memory: MemorySettings = Field(
        default_factory=MemorySettings, description="Long-term memory configuration"
    )
    tools: ToolSettings = Field(
        default_factory=ToolSettings, description="Tool execution configuration"
    )
    server: ServerSettings = Field(
        default_factory=ServerSettings, description="Server configuration"
    )
    experiment: ExperimentSettings = Field(
        default_factory=ExperimentSettings, description="A/B experiment configuration"
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
