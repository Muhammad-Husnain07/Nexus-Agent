# `src/nexus/agent/` — LangGraph Orchestration

This module owns the LangGraph StateGraph that implements a **15-node production agent orchestration loop**. The agent contains **zero business logic** — it plans, executes tools in parallel via DAG waves, reflects on failures, and composes responses via LLM.

## Key Responsibilities

- Define `StateGraph` topology with **15 production nodes**: Router → Extraction → Normalization → ContextMerge → Validation → Clarification/Resolution → TaskGraphBuilder → GraphOptimizer/Planner → PlanValidator → ApprovalGate → Executor → Reflection → Response.
- Manage graph lifecycle: compile with checkpointer, stream updates, cache per process lifetime.
- Provide `AgentRunner` that wires LLM, tools, memory, event bus, checkpointer, and Redis distributed session lock.
- 3-stage planner pipeline: **ResolutionNode** (A* graph search, no LLM) → **TaskGraphBuilderNode** (topological DAG) → **GraphOptimizerNode** (policy-based tool selection). Falls through to **PlannerNode** (LLM) when deterministic resolution fails.
- Entity extraction + normalization + validation pipeline — pure Python validation, no LLM.
- Pre-execution plan validation via `PlanValidatorNode` — checks cycles, prerequisites, root nodes.
- Self-reflection via `ReflectionNode` — auto-retries failed tasks up to configured max with exponential backoff.
- HITL approval via `ApprovalGateNode` — driven by tool metadata (risk_level/requires_approval), per-call scope with inputs, approval expiry.
- Named checkpoint recovery — restore graph to state before any node.
- Post-execution metrics extraction from checkpoint history — per-node timing, tokens, DAG size.
- Versioned routing memory — feedback records tagged with embedding_model/registry_version/planner_version.
- State management via `state_schema.py` — 3-tier TypedDict with rolling-window message reducer, background task tracking.

## Key Files

| File | Responsibility |
|------|---------------|
| `graph.py` | `build_agent_graph()` — constructs 15-node graph with 7 conditional routing functions |
| `runner.py` | `AgentRunner` — module-level graph cache, `invoke()` async generator, Redis distributed lock with heartbeat, SSE event translation with `node_completed` timing, `continue_after_approval()`, `recover()`, `resume()`, background task tracking |
| `state_schema.py` | Production `AgentState` TypedDict (60+ fields, 3-tier nested + flat compat), Pydantic models (`ToolResult`, `ExecutionGraph`, `CostTracker`, `MessageHistory`, `MessageEntry`), reducers, `_EPHEMERAL_FIELDS` (33 fields) |
| `state/context.py` | `StructuredContext` — single source of truth with `EntitySet`, `business_requirements`, `metadata`, `user_decisions`, `trace_id`, `reset_for_new_intent()` |
| `state.py` | Backward-compat shim re-exporting from `state_schema` |
| `router.py` | Two-stage query classifier (heuristic ~0ms + LLM fallback), `QueryType` enum, weighted keyword index (names 5.0, keywords 1.0, tags 0.8, aliases 1.5) |
| `planners/dag_planner.py` | Hybrid DAG planner — `_deterministic_plan()` (single-tool/compare/keyword pattern match, no LLM) + `_llm_propose_tasks()` (LLM fallback). Prerequisite injection, cycle detection (DFS), topological sort (Kahn's) into Execution Waves |
| `planners/dependency_analysis.py` | Shared I/O schema dependency analysis — used by both router and planner. `build_signatures()`, `analyze_dependencies()`, `has_schema_dependency()`, `find_unmet_inputs()` |
| `executors/concurrent_executor.py` | Wave-based `asyncio.gather` executor with fault isolation (`return_exceptions=True`), exponential backoff retry, per-tool + global timeout, Semaphore-based concurrency, placeholder resolution (`${task_id.result.field}`) |
| `nodes/extraction_node.py` | LLM-only intent + entity extraction. Single-intent (prompt v1) and multi-intent (prompt v2). On failure returns distinguishable `extraction_error` intent. Captures cost/tokens on both success and failure paths |
| `nodes/normalization_node.py` | Pure Python entity normalization — dates ("today"→ISO), locations ("NYC"→"New York City"), currencies ("$"→"USD"). No LLM. Returns `_normalization_metadata` |
| `nodes/context_merge_node.py` | Merges extraction into StructuredContext — handles new context, intent change reset, additive/correction merge. Merges business_requirements and normalization metadata |
| `nodes/validation_node.py` | 4-stage deterministic validation pipeline — intent exists + multi-intent support, apply defaults, required fields with type/format validators, low confidence threshold. No LLM |
| `nodes/clarification_node.py` | Asks for missing info, enriches with router's `_preferred_tools` signal, appends to messages, persists to memory via `memory_helper.py`. Ends graph |
| `nodes/resolution_node.py` | Stage 1 of 3-stage planner. A* graph search over CapabilityRegistry capability graph. Pure Python, no LLM. Falls through to PlannerNode if no chain found |
| `nodes/task_graph_builder_node.py` | Stage 2 of 3-stage planner. Converts resolved capability chain into topological DAG with dependency edges based on consumes/produces |
| `nodes/graph_optimizer_node.py` | Stage 3 of 3-stage planner. Policy-based tool selection (cost weight 0.5, latency 0.3). Picks optimal tool per capability from available tools |
| `nodes/plan_validator_node.py` | Pre-execution DAG validation — checks root nodes exist, no cycles (DFS), all required inputs satisfied. Routes to ClarificationNode on failure |
| `nodes/finalize.py` | Composes final response via LLM from tool results. Uses `MemoryScout` for semantic memory, `WorkingMemory` for context injection. Persists via `memory_helper.py`. Sets `response_type` based on outcome |
| `nodes/memory_helper.py` | Shared memory persistence — persists to WorkingMemory + Redis Stream `memory_extraction_queue` or MemoryManager fallback. Used by both finalize and clarification nodes. Background tasks tracked to prevent GC |
| `checkpoint_manager.py` | Named checkpoint lookup via LangGraph state history — `find_checkpoint_before()` for ANY node name, `find_latest_checkpoint()` (penultimate). No hardcoded node names |
| `metrics.py` | Post-execution metrics extraction from checkpoint history. Computes per-node latency, total tokens, DAG size, retry count, router decision path. No live latency impact |
| `routing_memory.py` | Versioned routing feedback — `RoutingFeedback` model with `embedding_model`, `registry_version`, `planner_version`. Redis storage with 24h TTL. `find_similar_routing()` filters by exact version match |
| `registry/intent_registry.py` | Dynamic IntentRegistry — auto-populated from tool schemas at invoke time. Built-in validators (latitude, longitude, url, email, positive_int, non_empty_string) |
| `registry/goal_registry.py` | Dynamic GoalRegistry — goals auto-inferred from tool categories, name prefixes, and tags. Maps goal names to capabilities |
| `registry/capability_registry.py` | Dynamic CapabilityRegistry with `consumes`/`produces`/`preconditions`/`postconditions`. `find_chain()` BFS over capability graph |
| `registry/artifact_registry.py` | `ArtifactType` enum (DATA/STATE/DECISION/REFERENCE), `Artifact` model with JSON Schema validation, trace_id, TTL. Auto-inferred from tool I/O schemas |
| `registry/normalization_registry.py` | Pluggable entity normalizers — date, location, currency, text. Matched by field name keywords |
| `prompts/manager.py` | Central prompt registry with versioning and A/B testing |
| `prompts/extraction.py` | Extraction prompt v1 (single-intent) and v2 (multi-intent) |
| `prompts/planner.py` | Planner task proposal prompt — registered via prompt_manager |
| `errors.py` | Re-exports agent-specific exceptions from central error module |

## Graph Architecture (15 Nodes)

```
START → RouterNode
  │
RouterNode ──→ ExtractionNode → NormalizationNode → ContextMergeNode → ValidationNode
  │
ValidationNode ──route_after_validation()──→ ResolutionNode | ClarificationNode → END
  │                                              │
  │                                         ┌────┴────┐
  │                                         ▼         ▼
  │                                  TaskGraphBuilder   PlannerNode (LLM fallback)
  │                                         │              │
  │                                  GraphOptimizer        │
  │                                         └──────┬───────┘
  │                                                ▼
  │                                         PlanValidatorNode
  │                                         ──route_after_plan_validator()──
  │                                         │                              │
  │                                         ▼                              ▼
  │                                  ApprovalGateNode              ClarificationNode → END
  │                                         │
  │                                  route_after_approval_gate()
  │                                         │
  │                                    ExecutorNode
  │                                         │
  │                                    route_after_executor()
  │                                         │
  │                                    ReflectionNode
  │                                         │
  │                                    route_after_reflection()
  │                                         │
  │                                    ResponseNode → END
```

### Node Details

| Node | Stage | Behaviour |
|------|-------|-----------|
| `RouterNode` | Classification | Two-stage: heuristic (~0ms weighted keyword index) + LLM fallback (~500ms). Sets `_query_type`, `_preferred_tools`, `response_type` |
| `ExtractionNode` | Extraction | LLM-only intent + entity extraction. Single-intent prompt v1, multi-intent v2. On failure returns `extraction_error` (distinguishable from `unknown`). Captures cost on both paths |
| `NormalizationNode` | Normalization | Pure Python entity normalization — dates ("today"→ISO), locations ("NYC"→"New York City"), currencies ("$"→"USD"), text cleanup |
| `ContextMergeNode` | Merge | Incremental context updates: first extraction creates fresh, intent change resets, same intent merges additively or correctively |
| `ValidationNode` | Validation | 4-stage deterministic pipeline — intent exists (with multi-intent support), apply defaults, required fields + type validators (latitude, url, email, etc.), low confidence threshold |
| `ClarificationNode` | Clarification | Reads `_validation_result`, enriches with router's `_preferred_tools`, appends to `messages[]`, persists to memory. **Edge to END** |
| `ResolutionNode` | Planner Stage 1 | A* graph search over Capability Registry's capability graph. Pure Python, no LLM. Finds valid capability chain from user artifacts to goal. Falls through to PlannerNode |
| `TaskGraphBuilderNode` | Planner Stage 2 | Converts capability chain into topological DAG with dependency edges based on each capability's `consumes`/`produces` fields |
| `GraphOptimizerNode` | Planner Stage 3 | Policy-based tool selection (cost weight 0.5, latency 0.3). Picks optimal tool per capability from available tools |
| `PlannerNode` | Planner Fallback | Hybrid deterministic + LLM. Fast-path guard for approved plans. `_deterministic_plan()` pattern matches single-tool/compare/keyword queries. Falls through to `_llm_propose_tasks()` for complex DAGs |
| `PlanValidatorNode` | Pre-Execution | Pure Python DAG validation: checks cycles (DFS), root nodes exist, all required inputs satisfied. Routes to ClarificationNode on failure |
| `ApprovalGateNode` | HITL | Checks each tool's `risk_level`/`requires_approval`. Per-call scope with inputs. Approval expiry auto-reject. Routes to ExecutorNode (`"approved"`) or ResponseNode (otherwise) |
| `ExecutorNode` | Execution | Wave-based concurrent tool execution via `ConcurrentExecutor`. `asyncio.gather(return_exceptions=True)` within waves, `asyncio.wait_for` per tool |
| `ReflectionNode` | Reflection | Checks failures, retries with configurable max (settings). Sets `_recovery_available` on max retries |
| `ResponseNode` | Response | Returns existing response (greeting/approval/clarification) or delegates to `finalize()` for LLM composition. Sets `response_type` based on outcome |

## 5-Tier Abstraction Hierarchy

```
Intent → Goal → Capability → Artifact → Tool
```

| Tier | Registry | Source | Example |
|------|----------|--------|---------|
| **Intent** | `IntentRegistry` | Inferred from tool name/purpose | `"get_weather"`, `"compare_prices"` |
| **Goal** | `GoalRegistry` | Inferred from tool category/prefix | `"weather_retrieval"`, `"data_retrieval"` |
| **Capability** | `CapabilityRegistry` | Inferred from tool tags/prefix | `"search"`, `"get_operations"` — with `consumes`, `produces`, `preconditions`, `postconditions` |
| **Artifact** | `ArtifactRegistry` | Inferred from tool I/O schemas | `"get_weather.latitude"`, `"get_weather.temperature"` — typed with JSON Schema |
| **Tool** | `ToolRegistry` | Explicit registration | `get_weather`, `web_search` |

The `ResolutionNode` uses A* over the Capability graph to find transformation paths. The `GraphOptimizerNode` selects the optimal tool per capability based on cost/latency policy.

## State Schema (3-Tier)

| Tier | Fields | Checkpointed | Lifecycle |
|------|--------|-------------|-----------|
| `persistent` | `session_id`, `user_context`, `approved_tools`, `config_overrides` | Always | Survives across turns |
| `working` | `messages`, `current_plan` (ExecutionGraph), `tool_results_buffer`, `gathered_requirements` | Per-turn | Cleared after task completion |
| `cost` | `total_cost_usd`, `total_tokens`, `per_node` | Per-turn | Cost tracking only |

Ephemeral flags (33 fields: `_routing_decision`, `_query_type`, `_executor_failed`, `_needs_approval`, `_extraction_result`, `_validation_result`, `_resolution_chain`, etc.) live in `_EPHEMERAL_FIELDS` — cleared between turns, never in checkpoint state. **`_structured_context` is NOT ephemeral** — it's the Single Source of Truth.

## Reducers

| Field | Reducer | Behaviour |
|-------|---------|-----------|
| `messages` | `messages_reducer` | Rolling window (last 10 + milestones), dedup by ID, handles both dict and `MessageEntry` |
| `tool_results_buffer` | `tool_results_reducer` | Append-only, hard bound at 20 entries |

## LLM Call Counts Per Query Type

| Query Type | LLM Calls | When |
|------------|-----------|------|
| Greeting / Meta ("Hi", "What tools?") | 0 | Heuristic + template response |
| Single-tool with deterministic match ("Pikachu") | 2 | extraction + finalize (planner skipped by `_deterministic_plan()`) |
| Complex single-tool ("tell me a joke") | 3 | extraction + planner (LLM) + finalize |
| Multi-tool with deterministic match ("Bitcoin + news") | 2 | extraction + finalize (planner: Resolution + TaskGraphBuilder + GraphOptimizer, no LLM) |
| Multi-tool complex ("weather Paris + books + jokes") | 3 | extraction + planner (LLM) + finalize |
| Retry (on partial failure) | +1 | Per retry cycle |
| Clarification (router ambiguous) | +1 | If LLM fallback fires |

## Prompts Used

| Prompt File | Version | Used By |
|-------------|---------|---------|
| `finalize.py` | v3.0 | `finalize` node — response composition |
| `extraction.py` | v1.0 / v2.0 | `extraction_node` — single or multi-intent extraction |
| `planner.py` | v1.0 | `dag_planner.py` — LLM task proposal fallback |

All prompts registered via `PromptManager` with versioning.

## Event Types

| Event | Payload | Emitted By |
|-------|---------|------------|
| `node_completed` | `{node, duration_ms, has_output}` | Every node |
| `tool_selected` | `{intent, parameters: {query_type, preferred_tools}}` | RouterNode |
| `plan_created` | `{steps: {waves, tool_names, dependencies}}` | PlannerNode / TaskGraphBuilder |
| `tool_call_completed` | `{tool_name, status, data, error, task_id}` | ExecutorNode per tool |
| `final_response` | `{text}` | ResponseNode / ClarificationNode |
| `approval_required` | `{pending_tools, message}` | ApprovalGateNode |
| `reflection_result` | `{score, feedback, reflection_count}` | ReflectionNode |
| `error` | `{message}` | Any node |

## Test Suite

| Test | Type | Location |
|------|------|----------|
| YAML Scenario Test Runner | Integration | `tests/run_scenarios.py` + `tests/scenarios/*.yaml` — asserts on graph state (router, extraction, planner, executor) |
| Ephemeral Fields Drift | Unit | `tests/test_ephemeral_fields.py` — detects when `_EPHEMERAL_FIELDS` drifts from `AgentState` annotations |
| All 20 Tools | Integration | `scripts/test_all_tools.py` — tests every registered tool via API test endpoint |

## Dependencies

- `nexus/llm/` — LLMClient for all model calls (always returns `LLMResponse` with cost data, even on failure)
- `nexus/tools/` — ToolRegistry, ToolExecutor, DynamicToolSelector, approval_gate
- `nexus/sessions/` — SessionService for message persistence
- `nexus/memory/` — MemoryManager, AsyncPostgresSaver checkpointer
- `nexus/redis_client/` — EventBus for streaming agent events, distributed lock
- `nexus/db/` — async_session factory for tool execution persistence
