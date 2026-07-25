# `src/nexus/agent/` — LangGraph Orchestration

This module owns the LangGraph StateGraph that implements an 11-node production agent orchestration loop. The agent contains **zero business logic** — it plans, executes tools in parallel via DAG waves, reflects on failures, and composes responses via LLM.

## Key Responsibilities

- Define `StateGraph` topology with **11 production nodes** (Router → Extraction → Normalization → ContextMerge → Validation → Clarification/Planner → ApprovalGate → Executor → Reflection → Response).
- Manage graph lifecycle: compile with checkpointer, stream updates, cache per process lifetime.
- Provide `AgentRunner` that wires LLM, tools, memory, event bus, checkpointer, and Redis distributed session lock.
- DAG-based parallel tool execution via `ConcurrentExecutor` (wave-based `asyncio.gather`).
- Entity extraction + normalization + validation pipeline — pure Python validation, no LLM.
- Self-reflection via `ReflectionNode` — auto-retries failed tasks up to configured max with exponential backoff.
- HITL approval via `ApprovalGateNode` — driven by tool metadata (risk_level/requires_approval), no hardcoded tool names.
- Named checkpoint recovery — restore graph to state before any node (PlannerNode, ExecutorNode, etc.).
- State management via `state_schema.py` — 3-tier TypedDict with rolling-window message reducer.

## Key Files

| File | Responsibility |
|------|---------------|
| `graph.py` | `build_agent_graph()` — constructs 11-node graph with conditional edges |
| `runner.py` | `AgentRunner` — module-level graph cache, `invoke()` async generator, Redis distributed lock, SSE event translation, `continue_after_approval()`, `recover()` |
| `state_schema.py` | Production `AgentState` TypedDict (60+ fields, 3-tier nested + flat compat), Pydantic models (`ToolResult`, `ExecutionGraph`, `CostTracker`, `MessageHistory`), reducers |
| `state/context.py` | `StructuredContext` — single source of truth with `EntitySet`, `business_requirements`, `metadata`, `user_decisions` |
| `router.py` | Two-stage query classifier (heuristic ~0ms + LLM fallback ~500ms), `QueryType` enum |
| `planners/dag_planner.py` | Dynamic DAG planner — dependency analysis, prerequisite injection, cycle detection via DFS, topological sort into Execution Waves |
| `planners/dependency_analysis.py` | Shared I/O schema dependency analysis — used by both router and planner |
| `executors/concurrent_executor.py` | Wave-based `asyncio.gather` executor with fault isolation, exponential backoff retry, per-tool + global timeout, placeholder resolution |
| `nodes/extraction_node.py` | LLM-only intent + entity extraction. Supports single and multi-intent via prompt v2. On failure returns distinguishable `extraction_error` intent |
| `nodes/normalization_node.py` | Pure Python entity normalization — dates, locations, currencies. No LLM |
| `nodes/context_merge_node.py` | Merges extraction into StructuredContext — handles new context, intent changes, corrections |
| `nodes/validation_node.py` | 5-stage deterministic validation pipeline — intent exists, defaults, required fields, validators, confidence |
| `nodes/clarification_node.py` | Asks for missing info, enriches with router's `_preferred_tools`, appends to messages, persists to memory |
| `nodes/finalize.py` | Composes final response via LLM from tool results, persists episodic memory via shared `memory_helper.py` |
| `nodes/memory_helper.py` | Shared memory persistence — used by both finalize and clarification nodes |
| `checkpoint_manager.py` | Named checkpoint lookup via LangGraph state history — `find_checkpoint_before()` and `find_latest_checkpoint()` |
| `registry/intent_registry.py` | Dynamic IntentRegistry — auto-populated from tool schemas at invoke time |
| `registry/capability_registry.py` | Dynamic capability inference from tool metadata — no hardcoded capabilities |
| `registry/normalization_registry.py` | Pluggable entity normalizers — date, location, currency, text. Matched by field name pattern |
| `prompts/manager.py` | Central prompt registry with versioning and A/B testing |
| `prompts/extraction.py` | Extraction prompt v1 (single-intent) and v2 (multi-intent) |
| `prompts/planner.py` | Planner task proposal prompt — registered via prompt_manager |
| `errors.py` | Re-exports agent-specific exceptions from central error module |

## Graph Architecture (11 Nodes)

```
RouterNode
  │
  └──→ ExtractionNode → NormalizationNode → ContextMergeNode → ValidationNode
         │
         ├──→ PlannerNode → ApprovalGateNode → ExecutorNode → ReflectionNode → ResponseNode → END
         │      (ready)
         │
         └──→ ClarificationNode → END
                (missing info)
```

| Node | File | Behaviour |
|------|------|-----------|
| `RouterNode` | `graph.py:router_node` | Classifies query type via heuristic + LLM fallback. Sets `_query_type`, `_preferred_tools`, `response_type` |
| `ExtractionNode` | `nodes/extraction_node.py` | LLM-only intent + entity extraction. Single-intent prompt v1, multi-intent v2. Captures cost even on failure |
| `NormalizationNode` | `nodes/normalization_node.py` | Pure Python entity normalization — dates ("today"→ISO), locations ("NYC"→"New York City"), currencies ("$"→"USD") |
| `ContextMergeNode` | `nodes/context_merge_node.py` | Merges extraction into StructuredContext — creates fresh, resets on intent change, additive/correction merge |
| `ValidationNode` | `nodes/validation_node.py` | 5-stage deterministic validation — no LLM. Checks intent exists, applies defaults, validates required fields + types + confidence |
| `ClarificationNode` | `nodes/clarification_node.py` | Reads validation result, enriches with router's partial signal (`_preferred_tools`), appends to messages, persists to memory. Ends graph |
| `PlannerNode` | `graph.py:planner_node` | Filters relevant tools + capability context, calls DAG planner. Fast-path guard: approved plans skip LLM |
| `ApprovalGateNode` | `graph.py:approval_gate_node` | Checks each tool's risk_level/requires_approval. First pass → asks user. Resume → approved/rejected. Expiry auto-reject |
| `ExecutorNode` | `graph.py:executor_node` | Executes all DAG waves via `ConcurrentExecutor` — parallel within wave, sequential across waves |
| `ReflectionNode` | `graph.py:reflection_node` | Checks failures. Routes to retry (PlannerNode) or finalize (ResponseNode). Max retries from settings |
| `ResponseNode` | `graph.py:response_node` | Returns existing response (greeting/approval/clarification) or delegates to `finalize()` for LLM composition |

## State Schema (3-Tier)

| Tier | Fields | Checkpointed | Lifecycle |
|------|--------|-------------|-----------|
| `persistent` | `session_id`, `user_context`, `approved_tools`, `config_overrides` | Always | Survives across turns |
| `working` | `messages`, `current_plan` (ExecutionGraph), `tool_results_buffer`, `gathered_requirements` | Per-turn | Cleared after task completion |
| `cost` | `total_cost_usd`, `total_tokens`, `per_node` | Per-turn | Cost tracking only |

Ephemeral flags (32+ fields: `_routing_decision`, `_query_type`, `_executor_failed`, `_needs_approval`, `_extraction_result`, `_validation_result`, etc.) live in `_EPHEMERAL_FIELDS` — cleared between turns, never in checkpoint state. **`_structured_context` is NOT ephemeral** — it's the Single Source of Truth.

## Reducers

| Field | Reducer | Behaviour |
|-------|---------|-----------|
| `messages` | `messages_reducer` | Rolling window (last 10 + milestones), dedup by ID, handles both dict and `MessageEntry` |
| `tool_results_buffer` | `tool_results_reducer` | Append-only, hard bound at 20 entries |

## LLM Call Counts Per Query Type

| Query Type | LLM Calls |
|------------|-----------|
| Greeting / Meta ("Hi", "What tools?") | 0 (heuristic + template response) |
| Single-tool ("Tell me about Pikachu") | 3 (extraction + planner + finalize) |
| Independent multi ("weather + joke") | 3 (extraction + planner + finalize) |
| Dependent multi ("geocode → weather") | 3 (extraction + planner + finalize) |
| Retry (on partial failure) | +1 per retry cycle |
| Clarification (router ambiguous) | +1 if LLM fallback fires |

## Prompts Used

| Prompt File | Version | Used By |
|-------------|---------|---------|
| `finalize.py` | v3.0 | `finalize` node — response composition |
| `extraction.py` | v1.0 / v2.0 | `extraction_node` — single or multi-intent extraction |
| `planner.py` | v1.0 | `dag_planner.py` — LLM task proposal |

All prompts registered via `PromptManager` with versioning.

## Dependencies

- `nexus/llm/` — LLMClient for all model calls
- `nexus/tools/` — ToolRegistry, ToolExecutor, DynamicToolSelector, approval_gate
- `nexus/sessions/` — SessionService for message persistence
- `nexus/memory/` — MemoryManager, PostgresSaver checkpointer
- `nexus/redis_client/` — EventBus for streaming agent events
- `nexus/db/` — async_session factory for tool execution persistence
