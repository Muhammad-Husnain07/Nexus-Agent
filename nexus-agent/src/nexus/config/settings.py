"""Application settings via Pydantic BaseSettings with nested groups."""

from functools import lru_cache
from typing import Any, Literal, get_args

# Supported prompt format identifiers — fully dynamic, no hardcoded model mappings
_PROMPT_FORMATS = Literal[
    "auto", "anthropic", "openai", "gemini", "deepseek", "llama", "qwen", "mistral", "raw"
]
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
    max_input_tokens: int = Field(
        default=128000,
        ge=1,
        description="Max input context window (fallback if model not in LiteLLM registry)",
    )
    supports_streaming: bool = Field(default=True, description="Supports streaming responses")
    supports_tools: bool = Field(default=True, description="Supports tool/function calling")
    supports_structured_output: bool = Field(
        default=False, description="Supports JSON structured output"
    )
    supports_output_dimensions: bool = Field(
        default=False,
        description="Supports setting output vector dimensions (OpenAI text-embedding-3-*)",
    )
    default_headers: dict[str, str] = Field(
        default_factory=dict, description="Default HTTP headers for API requests"
    )
    extra_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description='Extra kwargs passed to the provider (e.g. {"options": {"think": false}} for Qwen)',
    )
    prompt_format: str = Field(
        default="auto",
        description="Prompt format for this provider. 'auto' = runtime probe detect. Options: "
        + ", ".join(PROMPT_FORMAT_VALUES),
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
    # MODEL-AB-01 hybrid synthesis: an optional model override for the
    # FINAL SYNTHESIS only (empty = use default_model). Lets the planner
    # stay on the fast model while a stronger model composes the response
    # (Config D/E — Nano planner + Step/Ultra synthesis). Planner/
    # decomposition/extraction still use default_model.
    synthesis_model: str = Field(
        default="", description="Optional model override for final synthesis (empty = default)"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small", description="Default embedding model"
    )
    embedding_dimensions: int = Field(
        default=4096,
        ge=1,
        description="Output dimensions for the embedding column (must match DB VECTOR(n))",
    )
    timeout_s: int = Field(default=45, ge=1, description="Request timeout in seconds")
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

    base_threshold: float = Field(
        default=0.7, ge=0, le=1, description="Base acceptance score threshold"
    )
    domain_thresholds: dict[str, float] = Field(
        default_factory=lambda: {"tool": 0.8, "greeting": 0.5, "meta": 0.6, "memory_query": 0.7},
        description="Per-response-type threshold overrides",
    )
    convergence_delta: float = Field(
        default=0.02, ge=0, le=1, description="Min score delta to continue"
    )
    convergence_window: int = Field(default=2, ge=1, description="Rounds of low delta to stop")
    max_escalation_rounds: int = Field(
        default=2, ge=0, description="Rounds before model escalation"
    )
    self_consistency_k: int = Field(
        default=3, ge=1, le=10, description="Parallel samples for uncertainty"
    )
    self_consistency_early_stop: bool = Field(
        default=True, description="Stop early if samples agree"
    )
    max_concurrent_tasks: int = Field(default=5, ge=1, le=50, description="Max parallel tool calls")
    cost_budget_usd: float = Field(default=0.50, ge=0, description="Max API cost per task")
    max_speculative_approaches: int = Field(
        default=3, ge=1, le=10, description="Max parallel speculative branches per task"
    )
    speculative_timeout_s: float = Field(
        default=15.0, ge=1, description="Timeout per speculative branch"
    )
    max_dag_generations: int = Field(
        default=3, ge=1, le=10, description="Max recursive DAG expansion depth"
    )
    confidence_high: float = Field(
        default=0.9, ge=0, le=1, description="Proceed directly threshold"
    )
    confidence_moderate: float = Field(
        default=0.7, ge=0, le=1, description="Self-consistency band start"
    )
    confidence_low: float = Field(default=0.5, ge=0, le=1, description="Clarification threshold")


class RequirementCollectorSettings(BaseModel):
    """RequirementCollectorNode — interactive requirement gathering configuration.

    Controls the clarification loop: how many rounds to ask, when to skip,
    and how to format questions.
    """

    max_rounds: int = Field(
        default=8,
        ge=1,
        le=50,
        description="Max clarification rounds before forcing plan or aborting",
    )
    min_confidence_to_skip: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Confidence threshold above which the collector is skipped entirely",
    )
    min_confidence_to_proceed: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Confidence threshold above which planning proceeds with partial info",
    )
    question_max_tokens: int = Field(
        default=256,
        ge=32,
        le=2048,
        description="Max LLM tokens for generating a clarification question",
    )
    knowledge_max_tokens: int = Field(
        default=2000,
        ge=128,
        le=16384,
        description="Max LLM tokens for KnowledgeAssistantNode response",
    )
    knowledge_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="LLM temperature for knowledge-only queries",
    )


class AgentSettings(BaseModel):
    """LangGraph agent execution configuration.

    Fields:
        max_iterations: Maximum agent iterations per conversation turn.
        context_window_tokens: Maximum context window in tokens.
        summarization_threshold_tokens: Token count triggering summarization.
        max_planning_tools: Max tools to pass to the planner.
        global_execution_timeout_s: Global timeout for all execution waves.
        max_reflection_retries: Max retries before finalizing.
        extraction_max_tokens: Max LLM tokens for extraction node.
        extraction_temperature: LLM temperature for extraction.
        planner_max_tokens: Max LLM tokens for planner.
        fallback_confidence: Confidence when heuristic fallback matches intent.
        fallback_max_tools: Max tools in fallback plan (LLM returned nothing).
        max_result_chars: Max chars per tool result before truncation.
        max_result_list_items: Max items per list in tool result truncation.
        finalize_temperature: LLM temperature for response composition.
        finalize_max_tokens: Max LLM tokens for final response.
        milestone_min_length: Min response length to qualify as milestone.
        max_intent_display: Max intents to show in extraction prompt.
        adaptive_reflection: Adaptive reflection and uncertainty settings.
        max_invocation_wall_time_ms: Per-invocation ReasoningBudget wall clock.
        max_graph_steps: Max graph node steps per invocation (budget).
        max_replans: Max TOTAL replans per invocation (validator + compiler +
            recovery share ONE budget counter — an identical failure can
            never trigger an identical replan indefinitely).
        max_recovery_attempts: Max recovery attempts per invocation.
        max_llm_calls: Max LLM calls per invocation.
        max_tool_calls: Max tool calls per invocation.
        max_invocation_cost_usd: Max estimated cost per invocation.
        enable_claim_entailment: OPTIONAL claim→artifact entailment verifier
            (P2-A). Off by default: the deterministic incorporation/coverage
            guards + renderer are ALWAYS the correctness floor — the LLM
            entailment check, when enabled, runs only AFTER them and its
            failure degrades to the same deterministic renderer; it can
            never be the authority (a response can never claim success
            merely because an LLM says the claim is grounded).
    """

    max_iterations: int = Field(default=25, ge=1, description="Max iterations per turn")
    max_invocation_wall_time_ms: int = Field(
        default=180_000, ge=1_000, description="Per-invocation ReasoningBudget wall clock (ms)"
    )
    max_graph_steps: int = Field(
        default=50, ge=1, description="Max graph node steps per invocation"
    )
    max_replans: int = Field(
        default=4, ge=1, description="Max TOTAL replans per invocation (shared)"
    )
    max_recovery_attempts: int = Field(
        default=3, ge=1, description="Max recovery attempts per invocation"
    )
    max_llm_calls: int = Field(default=30, ge=1, description="Max LLM calls per invocation")
    max_tool_calls: int = Field(default=40, ge=1, description="Max tool calls per invocation")
    max_invocation_cost_usd: float = Field(
        default=1.0, ge=0.0, description="Max estimated cost per invocation"
    )
    enable_claim_entailment: bool = Field(
        default=False,
        description="P2-A optional claim→artifact entailment verifier (off by "
        "default; the deterministic guard + renderer are always the floor)",
    )
    memory_default_ttl_s: int = Field(
        default=604800,
        ge=0,
        description="Default memory entry lifetime in seconds (7 days; 0 = no "
        "expiry — a bounded lifetime prevents stale context from being "
        "treated as current truth, the P1 freshness contract)",
    )
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
    max_planning_tools: int = Field(
        default=10, ge=1, le=50, description="Max tools passed to planner"
    )
    global_execution_timeout_s: int = Field(
        default=60, ge=1, description="Global execution timeout"
    )
    max_reflection_retries: int = Field(
        default=0, ge=0, le=10, description="Max retries before finalize"
    )
    quorum_threshold: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Max failed task ratio before quorum lost"
    )
    # Risk level ordering for multi-stage approval gating
    risk_order: dict[str, int] = Field(
        default_factory=lambda: {"low": 0, "medium": 1, "high": 2},
        description="Risk level → integer order for max-risk computation",
    )
    extraction_max_tokens: int = Field(
        default=512, ge=64, description="LLM max tokens for extraction"
    )
    extraction_temperature: float = Field(
        default=0.0, ge=0, le=1, description="LLM temperature for extraction"
    )
    planner_max_tokens: int = Field(default=2048, ge=128, description="LLM max tokens for planner")
    fallback_confidence: float = Field(
        default=0.6, ge=0, le=1, description="Heuristic fallback confidence"
    )
    fallback_max_tools: int = Field(
        default=5, ge=1, le=50, description="Max tools in fallback plan"
    )
    max_result_chars: int = Field(default=2000, ge=100, description="Max chars per tool result")
    max_result_list_items: int = Field(
        default=5, ge=1, le=100, description="Max list items in result"
    )
    finalize_temperature: float = Field(
        default=0.7, ge=0, le=2, description="LLM temp for final response"
    )
    finalize_max_tokens: int = Field(
        default=1024, ge=64, description="LLM max tokens for final response"
    )
    milestone_min_length: int = Field(
        default=20, ge=1, description="Min response length for milestone"
    )
    max_intent_display: int = Field(
        default=20, ge=1, le=100, description="Max intents in extraction prompt"
    )
    router_max_tokens: int = Field(
        default=256, ge=64, description="LLM max tokens for router classifier"
    )
    summarizer_max_tokens: int = Field(
        default=256, ge=64, description="LLM max tokens for context summarizer"
    )
    adaptive_reflection: AdaptiveReflectionSettings = Field(
        default_factory=AdaptiveReflectionSettings,
        description="Adaptive reflection and uncertainty settings",
    )
    requirement_collector: RequirementCollectorSettings = Field(
        default_factory=RequirementCollectorSettings,
        description="Requirement collector interactive loop settings",
    )


class CompilerSettings(BaseModel):
    """Compiler — deterministic codegen endpoint scoring configuration.

    Score = cost_weight * cost_per_call + latency_weight * (latency_p99_ms / latency_divisor)
    """

    cost_weight: float = Field(
        default=1.0, ge=0.0, description="Weight for cost in endpoint scoring"
    )
    latency_weight: float = Field(
        default=1.0, ge=0.0, description="Weight for latency in endpoint scoring"
    )
    latency_divisor: float = Field(
        default=1000.0, gt=0.0, description="Divisor to normalize latency_ms to seconds"
    )
    default_latency_ms: int = Field(
        default=1000, ge=1, description="Default latency when endpoint has none"
    )
    max_fixpoint_iterations: int = Field(
        default=5, ge=1, le=100, description="Max PassManager fixpoint iterations"
    )
    max_budget_usd: float = Field(
        default=0.50, ge=0.0, description="Max estimated cost before warning"
    )
    max_latency_ms: int = Field(
        default=30000, ge=1, description="Max estimated latency before warning"
    )
    max_workflow_nodes: int = Field(
        default=50, ge=1, le=200, description="Max nodes per compiled workflow"
    )
    # P2-A HIERARCHICAL MEGA-DAG PLANNING: when a single request's intent
    # graph exceeds this many executable units, the planner splits planning
    # into per-chunk extraction passes instead of one giant 20-30 node
    # structured output (the T132/U133/W135/S126 empty-plan class — Ultra
    # fails to emit very large workflows in one pass). Chunks are built
    # from the intent graph's dependency-ordered units, each planned
    # separately, then merged deterministically. <= threshold = the
    # existing single-shot path (no behavior change for normal queries).
    max_single_pass_intents: int = Field(
        default=12,
        ge=1,
        le=100,
        description="Intent units above this trigger hierarchical (chunked) planning",
    )
    chunk_size: int = Field(
        default=6,
        ge=1,
        le=20,
        description="Intent units per planning chunk in hierarchical mode",
    )
    optimizer_min_nodes: int = Field(
        default=3,
        ge=1,
        le=50,
        description="Graphs with at most this many nodes bypass the optimizer entirely (pass-manager fixpoint + checkpoint writes are pure overhead on tiny linear graphs; schema defaults/coercion are applied by the executor at call time)",
    )
    max_critique_rounds: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Max PlanCriticNode refinement rounds (0 = disabled)",
    )
    max_plan_validator_rounds: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Max PlanValidatorNode replan rounds before explicit failure",
    )
    background_threshold_ms: int = Field(
        default=15000,
        ge=0,
        description="Estimated latency at/above which the strategy marks the plan for background execution",
    )
    planner_budget_ms: int = Field(
        default=25000,
        ge=0,
        description="ExecutionBudget: planning over this budget degrades to the lightweight pipeline (optimizer/critic bypassed)",
    )
    synthesis_budget_ms: int = Field(
        default=20000,
        ge=0,
        description="ExecutionBudget: synthesis over this budget degrades to the deterministic Artifact Renderer",
    )
    max_replan_rounds: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Max ReplanNode replan rounds before explicit failure",
    )


class CapabilityResolverSettings(BaseModel):
    """DynamicCapabilityResolver — multi-factor endpoint scoring configuration.

    Score is a weighted sum of normalized factors.  Higher is better.
    Each factor is normalized to [0.0, 1.0] before weighting.

    Factors:
        capability_match: Exact match on logical_op_name (always 1.0 or 0.0 — enforced by instructor).
        schema_match: How well the required inputs match what's available (from SchemaMatcher).
        reliability_success_rate: EWMA reliability score from ProviderModel.
        latency_score: Inversely proportional to latency_p99_ms (lower latency = higher score).
        cost_score: Inversely proportional to cost_per_call (lower cost = higher score).
        permissions_match: Whether user context satisfies required_permissions.
        version_recency: Newer API versions get a higher score.
        non_deprecated: Deprecated endpoints receive a penalty.
    """

    capability_match_weight: float = Field(
        default=2.0, ge=0.0, description="Weight for capability match score"
    )
    schema_match_weight: float = Field(
        default=1.5, ge=0.0, description="Weight for input schema match score"
    )
    reliability_weight: float = Field(
        default=1.5, ge=0.0, description="Weight for EWMA reliability score"
    )
    latency_weight: float = Field(
        default=1.0, ge=0.0, description="Weight for normalized latency score"
    )
    cost_weight: float = Field(default=1.0, ge=0.0, description="Weight for normalized cost score")
    permissions_weight: float = Field(
        default=2.0, ge=0.0, description="Weight for permissions match score"
    )
    user_preference_weight: float = Field(
        default=0.5, ge=0.0, description="Weight for user preference signal"
    )
    version_weight: float = Field(default=0.5, ge=0.0, description="Weight for API version recency")
    deprecated_penalty: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Score multiplier for deprecated endpoints (applied after sum)",
    )
    # D10 EMBEDDING A/B: nv-embed-v1 semantic retrieval as an ADDITIONAL
    # candidate-pool source (pgvector cosine over tool embeddings).
    # Embeddings RETRIEVE; the deterministic ranker + CapabilitySemantics
    # still DECIDE. Flag-gated so the experiment is fully switchable —
    # baseline (off) vs experiment (on), byte-for-byte elsewhere.
    enable_embedding_retrieval: bool = Field(
        default=False,
        description="Add nv-embed-v1 semantic retrieval to the resolver candidate pool (D10 A/B)",
    )

    max_latency_ms: int = Field(
        default=5000, ge=1, description="Latency at or above this value scores 0.0"
    )
    max_cost_usd: float = Field(
        default=1.0, ge=0.01, description="Cost at or above this value scores 0.0"
    )
    default_reliability: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Default reliability for providers without EWMA data",
    )
    top_k_candidates: int = Field(
        default=3, ge=1, le=20, description="Number of candidate endpoints to return"
    )
    # Layered resolution (capabilities/resolution.py) — fuzzy safety net
    # parameters. Fuzzy matches below the threshold are NEVER auto-applied;
    # they escalate to LLM repair instead.
    fuzzy_scorer: str = Field(
        default="wratio",
        description="RapidFuzz scorer: ratio | partial_ratio | token_sort | token_set | wratio",
    )
    fuzzy_threshold: float = Field(
        default=95.0,
        ge=0.0,
        le=100.0,
        description="Minimum fuzzy match score (0-100) for automatic resolution",
    )
    use_alias_index: bool = Field(default=True, description="Enable explicit-alias O(1) resolution")
    use_domain_classification: bool = Field(
        default=True, description="Enable domain-first narrowing in resolution"
    )
    enable_llm_repair: bool = Field(
        default=True, description="Allow LLM repair (top-K) when all deterministic layers fail"
    )
    max_repair_candidates: int = Field(
        default=5, ge=1, le=20, description="Top-K candidates sent to LLM repair"
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
    max_domain_concurrency: int = Field(
        default=10, ge=1, le=100, description="Max concurrent calls per API domain"
    )
    sandbox_enabled: bool = Field(default=True, description="Enable sandboxed execution")
    allowed_hosts: list[str] = Field(
        default_factory=list,
        description="Allowed external hosts (glob patterns; '*' = allow all, empty + enabled = block ALL — configure explicitly)",
    )
    # Approval threshold: minimum risk level that requires HITL approval,
    # compared against ``agent.risk_order``. Defaults to "high" — any tool
    # whose risk_level ranks at or above this tier triggers the approval gate.
    # Operators can lower it to "medium" (or raise to an impossible tier) to
    # tighten or relax the gate without code changes.
    approval_min_risk: str = Field(
        default="high",
        description="Minimum risk level requiring human approval (per agent.risk_order)",
    )
    proxy_url: str | None = Field(
        default=None, description="HTTP proxy URL for tool calls (e.g. http://proxy:8080)"
    )
    http2_enabled: bool = Field(default=True, description="Enable HTTP/2 for tool calls")

    # Default User-Agent for outbound tool HTTP requests
    user_agent: str = Field(
        default="NexusAgent/1.0 (agentic-ai-platform; +https://github.com/anomalyco/nexus-agent)",
        description="User-Agent header for tool HTTP calls",
    )

    # Auth header name mappings — auth_type → HTTP header name
    auth_header_mappings: dict[str, str] = Field(
        default_factory=lambda: {
            "bearer": "Bearer",
            "basic": "Basic",
            "api_key": "X-API-Key",
            "oauth2": "Bearer",
        },
        description="Auth type → HTTP header name mapping",
    )

    # Python code injection keywords — any schema field matching these is rejected
    python_code_keywords: list[str] = Field(
        default_factory=lambda: [
            "code",
            "script",
            "python",
            "exec",
            "eval",
            "compile",
            "subprocess",
            "__import__",
            "importlib",
            "run_python",
            "exec_python",
            "sandbox_code",
        ],
        description="Field name keywords that indicate Python code injection (rejected)",
    )

    # Common field name map for semantic fix-up when inputs fail validation
    common_field_map: dict[str, str] = Field(
        default_factory=lambda: {
            "q": "query",
            "query": "q",
            "name": "title",
            "title": "name",
            "id": "identifier",
            "identifier": "id",
            "email": "email_address",
            "email_address": "email",
            "lat": "latitude",
            "latitude": "lat",
            "lon": "longitude",
            "longitude": "lon",
            "long": "lon",
            "city": "location",
            "location": "city",
        },
        description="Field name → common variant mapping for semantic input fix-up",
    )

    # Retryable HTTP status codes
    retryable_status_codes: list[int] = Field(
        default_factory=lambda: [408, 429, 500, 502, 503, 504],
        description="HTTP status codes that trigger automatic retry",
    )

    # MCP client retry settings
    mcp_retry_max_attempts: int = Field(
        default=3,
        ge=0,
        description="Max retry attempts for MCP transport errors",
    )
    mcp_retry_backoff_base_s: float = Field(
        default=1.0,
        ge=0,
        description="Base backoff in seconds for MCP retry",
    )
    mcp_retry_backoff_max_s: float = Field(
        default=30.0,
        ge=0,
        description="Max backoff in seconds for MCP retry",
    )

    # Sensitive field names for log masking
    sensitive_field_names: list[str] = Field(
        default_factory=lambda: [
            "authorization",
            "api_key",
            "api-key",
            "x-api-key",
            "apikey",
            "token",
            "secret",
        ],
        description="Header/field names whose values should be redacted in logs",
    )

    # C4/P0-C: tool ``auth_ref`` values (env-var references injected as
    # Authorization headers) are resolved ONLY when the ref is operator-
    # allowlisted. Empty (default) = no arbitrary env-var references —
    # closing the server-side secret-exfiltration channel.
    auth_ref_allowlist: list[str] = Field(
        default_factory=list,
        description="Operator-approved env-var names usable as tool auth_refs",
    )

    # Max request body size in bytes
    max_request_bytes: int = Field(
        default=1_000_000,
        ge=1,
        description="Max request body size in bytes",
    )

    # Field name aliases for placeholder resolution across chained tools.
    # When a step expects "latitude" but the tool returned "lat", these mappings
    # ensure the placeholder is still resolved.  Configurable via env:
    # NEXUS_TOOLS__FIELD_ALIASES={"latitude":"lat","longitude":"lon"}
    field_aliases: dict[str, str] = Field(
        default_factory=lambda: {
            "latitude": "lat",
            "longitude": "lon",
            "lat": "latitude",
            "lon": "longitude",
            "temperature": "temp",
            "temp": "temperature",
        },
        description="Field name → alias mappings for placeholder resolution",
    )

    # Performance-aware selection
    performance_weight: float = Field(
        default=0.4, ge=0, le=1, description="Performance vs relevance weight"
    )
    performance_window_minutes: int = Field(
        default=60, ge=1, description="Sliding window for metrics"
    )

    # Degradation detection
    degradation_error_rate: float = Field(
        default=0.3, ge=0, le=1, description="Error rate threshold for degradation"
    )
    degradation_latency_multiplier: float = Field(
        default=3.0, ge=1, description="Latency multiplier threshold"
    )
    degradation_min_samples: int = Field(
        default=5, ge=1, description="Min samples before degradation check"
    )
    degradation_cooldown_minutes: int = Field(
        default=15, ge=1, description="Cooldown before auto-recovery"
    )

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


class CacheSettings(BaseModel):
    """Compiler cache TTL configuration.

    Fields:
        parse_ttl: TTL in seconds for the ParseCache (LLM workflow extraction).
        plan_ttl: TTL in seconds for the PlanCache (compiled execution plans).
    """

    parse_ttl: int = Field(
        default=3600, ge=0, description="ParseCache TTL in seconds (0 = disabled)"
    )
    plan_ttl: int = Field(default=300, ge=0, description="PlanCache TTL in seconds (0 = disabled)")


class QueueSettings(BaseModel):
    """Task queue configuration.

    Fields:
        provider: Queue transport (``redis_streams`` default; external MQ
            adapters pluggable behind the provider interface).
        worker_poll_ms: Worker claim poll interval in milliseconds.
        retry_backoff_s: Base backoff between task retries in seconds.
    """

    provider: str = Field(
        default="redis_streams",
        description="Queue provider (redis_streams | <adapter>)",
    )
    worker_poll_ms: int = Field(default=500, ge=50, description="Worker claim poll interval (ms)")
    retry_backoff_s: float = Field(default=2.0, ge=0, description="Task retry backoff (s)")


class AuthSettings(BaseModel):
    """Authentication configuration.

    Fields:
        mode: ``none`` (default — embeddable passthrough), ``api_key``
            (static key header), or ``jwt`` (verifiable tokens).
        jwt_algorithm: Algorithm used to verify JWTs.
        jwt_issuer: Expected token issuer (optional).
        api_key_header: Header name carrying the static API key.
    """

    mode: str = Field(
        default="none",
        description="Auth mode: none | api_key | jwt",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing/verification algorithm")
    jwt_issuer: str | None = Field(default=None, description="Expected JWT issuer (optional)")
    api_key_header: str = Field(default="X-API-Key", description="Static API key header name")


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
    compiler: CompilerSettings = Field(
        default_factory=CompilerSettings, description="Compiler codegen configuration"
    )
    tools: ToolSettings = Field(
        default_factory=ToolSettings, description="Tool execution configuration"
    )
    resolver: CapabilityResolverSettings = Field(
        default_factory=CapabilityResolverSettings,
        description="Capability resolver scoring configuration",
    )
    server: ServerSettings = Field(
        default_factory=ServerSettings, description="Server configuration"
    )
    cache: CacheSettings = Field(
        default_factory=CacheSettings, description="Cache TTL configuration"
    )
    queue: QueueSettings = Field(
        default_factory=QueueSettings, description="Task queue configuration"
    )
    auth: AuthSettings = Field(
        default_factory=AuthSettings, description="Authentication configuration"
    )
    experiment: ExperimentSettings = Field(
        default_factory=ExperimentSettings, description="A/B experiment configuration"
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
