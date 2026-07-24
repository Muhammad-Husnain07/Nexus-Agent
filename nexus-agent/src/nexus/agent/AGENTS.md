# `src/nexus/agent/` — LangGraph Orchestration

This module owns the LangGraph StateGraph that implements a 5-node production agent orchestration loop. The agent contains **zero business logic** — it plans, executes tools in parallel via DAG waves, reflects on failures, and composes responses via LLM.

## Key Responsibilities

- Define `StateGraph` topology with **5 production nodes** (Router → Planner → Executor → Reflection → Response).
- Manage graph lifecycle: compile with checkpointer, stream updates, cache per process lifetime.
- Provide `AgentRunner` that wires LLM, tools, memory, event bus, and Redis distributed session lock.
- DAG-based parallel tool execution via `ConcurrentExecutor` (wave-based `asyncio.gather`).
- Self-reflection via `ReflectionNode` — auto-retries failed tasks up to 2 times with backoff.
- State management via `state_schema.py` — 3-tier TypedDict with rolling-window message reducer.

## Key Files

| File | Responsibility |
|------|---------------|
| `graph.py` | `build_agent_graph()` — constructs 5-node graph with conditional edges |
| `runner.py` | `AgentRunner` — module-level graph cache, `invoke()` async generator, Redis distributed lock, SSE event translation |
| `state_schema.py` | Production `AgentState` TypedDict (64 fields, 3-tier nested + flat compat), Pydantic models (`ToolResult`, `ExecutionGraph`, `CostTracker`, `MessageHistory`), reducers |
| `state.py` | Backward-compat shim re-exporting from `state_schema` + legacy models (`PlanStep`, `Plan`, `IntentAnalysis`) |
| `router.py` | Two-stage query classifier (heuristic ~0ms + LLM fallback ~500ms), `QueryType` enum (`SINGLE_TOOL`, `INDEPENDENT_MULTI`, `DEPENDENT_MULTI`, `CONVERSATIONAL`, `NO_TOOL_NEEDED`) |
| `planners/dag_planner.py` | Dynamic DAG planner — dependency analysis, implicit injection (geocode→weather), cycle detection via DFS, topological sort into Execution Waves |
| `executors/concurrent_executor.py` | Wave-based `asyncio.gather` executor with fault isolation, exponential backoff retry, per-tool + global timeout, placeholder resolution |
| `memory/context_manager.py` | Sliding window + LLM summarization for history, tool result truncation, relevance filtering |
| `nodes/finalize.py` | Composes final response via LLM from tool results, persists episodic memory, background Redis stream |
| `hitl.py` | HITL approval interrupt utilities (used by `tools/approval_gate.py`, not by graph nodes directly) |
| `errors.py` | Re-exports agent-specific exceptions from central error module |
| `schemas.py` | Request/response models: `AgentInvokeRequest`, `AgentStreamEvent`, `ApprovalAction`, etc. |

## Graph Architecture (5 Nodes)

```
RouterNode ────────────────────→ ResponseNode (NO_TOOL_NEEDED)
    │
    └──→ PlannerNode ──→ ExecutorNode ──→ ResponseNode (all success)
                                              ↑
                           ReflectionNode ─────┘ (max retries exceeded)
                                ↑
                           ExecutorNode ──→ ReflectionNode (partial failures)
                                │
                           ReflectionNode ──→ PlannerNode (retry needed)
```

| Node | File | Behaviour |
|------|------|-----------|
| `RouterNode` | `graph.py:router_node` | Classifies query type via heuristic + LLM fallback. Sets `_query_type` for routing. |
| `PlannerNode` | `graph.py:planner_node` | Filters relevant tools, calls `PlannerRunner.build_plan()` → DAG plan with waves + dependencies. |
| `ExecutorNode` | `graph.py:executor_node` | Executes all DAG waves via `ConcurrentExecutor` — parallel within wave, sequential across waves. |
| `ReflectionNode` | `graph.py:reflection_node` | Checks `_executor_failed`. Routes to retry (PlannerNode) or finalize (ResponseNode). Max 2 retries. |
| `ResponseNode` | `graph.py:response_node` | Delegates to `nodes/finalize.finalize()` — LLM composes natural response from tool results. |

## State Schema (3-Tier)

| Tier | Fields | Checkpointed | Lifecycle |
|------|--------|-------------|-----------|
| `persistent` | `session_id`, `user_context`, `config_overrides` | Always | Survives across turns |
| `working` | `messages`, `current_plan`, `tool_results_buffer`, `gathered_requirements` | Per-turn | Cleared after task completion |
| `cost` | `total_cost_usd`, `total_tokens`, `per_node` | Per-turn | Cost tracking only |

Ephemeral flags (30 fields: `_routing_decision`, `_query_type`, `_executor_failed`, etc.) live in `_EPHEMERAL_FIELDS` — cleared between turns, never in checkpoint state.

## Reducers

| Field | Reducer | Behaviour |
|-------|---------|-----------|
| `messages` | `messages_reducer` | Rolling window (last 10 + milestones), dedup by ID, handles both dict and `MessageEntry` |
| `tool_results_buffer` | `tool_results_reducer` | Append-only, hard bound at 20 entries |

## LLM Call Counts Per Query Type

| Query Type | LLM Calls |
|------------|-----------|
| Greeting / Meta ("Hi", "What tools?") | 0 (template response) |
| Single-tool ("Tell me a joke") | 2 (plan + finalize) |
| Independent multi ("weather + joke") | 2 (plan + finalize) |
| Dependent multi ("geocode → weather") | 2 (plan + finalize) |
| Retry (on partial failure) | +1 per retry cycle |

## Prompts Used

| Prompt File | Used By |
|-------------|---------|
| `finalize.py` (v3.0) | `finalize` node — response composition |
| `plan_parallel.py` (v1.0) | `dag_planner.py` — LLM task proposal |
| `understand_intent.py` (v4.0) | Legacy — prompt template only |

All other prompt templates (`reflect_on_response`, `gather_requirements`, `execute_step`, etc.) are retained as registered strings but unused by the active graph.

## Dependencies

- `nexus/llm/` — LLMClient for all model calls
- `nexus/tools/` — ToolRegistry, ToolExecutor, DynamicToolSelector
- `nexus/sessions/` — SessionService for message persistence
- `nexus/memory/` — MemoryManager, PostgresSaver checkpointer
- `nexus/redis_client/` — EventBus for streaming agent events
- `nexus/db/` — async_session factory for tool execution persistence
