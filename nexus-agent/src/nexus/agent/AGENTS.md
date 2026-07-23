# `src/nexus/agent/` — LangGraph Orchestration

This module owns the LangGraph StateGraph that implements a hybrid DAG-based Plan-and-Execute + Reflection reasoning loop. The agent contains **zero business logic** — it plans, reasons via DAG expansion, executes tools in parallel, reflects on responses, and routes to clarification when needed.

## Key Responsibilities

- Define `StateGraph` topology with **6 parent nodes** + **3-node tool subgraph**.
- Manage graph lifecycle: compile with checkpointer, stream updates, cache per session.
- Provide `AgentRunner` that wires LLM, tools, memory, event bus, and session lock.
- Human-in-the-Loop via `review_final_answer` / `review_plan` nodes and LangGraph `interrupt()`.
- DAG-based parallel tool execution inside the tool subgraph via `Send()` API.
- Self-reflection via `reflect_on_response` — scores responses and routes to `finalize`, `revise_finalize`, `revise`, or `clarify`.

## Key Files

| File | Responsibility |
|------|---------------|
| `graph.py` | `build_agent_graph()` — constructs parent graph with 6 nodes + tool subgraph |
| `runner.py` | `AgentRunner` — session-scoped graph cache, `invoke()` async generator, Redis distributed lock |
| `state.py` | `AgentState` TypedDict (28 fields), `IntentAnalysis`, `PlanStep`, `Plan` Pydantic models |
| `tool_subgraph.py` | DAG-based parallel executor subgraph using `Send()` API (3 nodes) |
| `hitl.py` | `interrupt_for_approval()` with 5 criteria, `build_approval_payload()`, `persist_interrupt()` |
| `hitl_middleware.py` | Wraps `ToolExecutor` to intercept calls requiring HITL approval |
| `feedback_interrupt.py` | Reusable `interrupt_for_feedback()` for approve/edit/reject patterns |
| `errors.py` | Re-exports agent-specific exceptions from central error module |
| `schemas.py` | Request/response models: `AgentInvokeRequest`, `AgentStreamEvent`, `ApprovalAction`, etc. |

## Parent Graph Nodes (6)

| Node | File | Behaviour |
|------|------|-----------|
| `understand_intent` | `understand_intent.py` | LLM parses user message into `IntentAnalysis` (primary_goal, needs_tool, response_type, confidence). Routes to `respond_without_tool`, `gather_requirements`, or `tool_subgraph`. |
| `respond_without_tool` | `respond_without_tool.py` | Handles greeting/meta/memory queries directly (no tool needed). |
| `gather_requirements` | `gather_requirements.py` | Asks clarifying questions. Routes to END (user replies with new message, re-entering at `understand_intent`). |
| `finalize` | `finalize.py` | Composes final response from tool results. Persists episodic memory for tool interactions. |
| `review_final_answer` | `review_final_answer.py` | Optional HITL interrupt — pauses for approve/edit/reject on final response. Requires `needs_human_review=true`. |
| `reflect_on_response` | `reflect_on_response.py` | LLM scores response quality. Routes: `finalize` (score >= 7), `revise_finalize` → `finalize` (regenerate), `revise` → `understand_intent` (re-plan), `clarify` → `gather_requirements` (ask user). |

## Tool Subgraph Nodes (3)

| Node | File | Behaviour |
|------|------|-----------|
| `discover_tools` | `discover_tools.py` | Semantic tool discovery via `DynamicToolSelector`. Entry point of subgraph. |
| `dag_expander` | `dag_expander.py` | Generates DAG plan via LLM (parallel tasks with dependencies). `route_dag` conditional edge fans out ready tasks via `Send()`. |
| `tool_executor` | `tool_executor.py` | Executes a single DAG task directly (no LLM — placeholder resolution + HTTP call). |

## Performance Optimizations & Removal Impact

| # | Optimization | File | What It Does | If Removed |
|---|---|---|---|---|
| **1** | **Single-tool fast path** | `dag_expander.py:58-68` | Skips LLM plan when only 1 tool available — generates direct task | **+1-5s latency** on every single-tool query. LLM must generate plan for every request. |
| **2** | **Tool schema pruning** | `dag_expander.py:70-95` | Strips non-required fields from tool schemas in plan prompt — 60% smaller prompt | **+2-3s latency** from larger prompts. More tokens = slower LLM generation. |
| **3** | **Redis plan cache** | `dag_expander.py:101-108** | Stores generated plans by intent hash. Reuses plan for identical intents. | **+1-5s latency** on repeated queries. Every request regenerates the plan. |
| **4** | **Skip reflection when tool succeeded** | `reflect_on_response.py:132-141` | Skips LLM reflection call when `_tool_executed_in_turn` is True | **+1-3s latency** per tool query. Every response gets scored unnecessarily. |
| **5** | **Greeting template (no LLM)** | `respond_without_tool.py:85-90` | Returns random greeting from static list instead of LLM call | **+300-800ms** per greeting. Every "Hi" becomes an LLM call. |
| **6** | **Memory extraction in background** | `finalize.py:215-220` | Moves memory extraction to `asyncio.ensure_future()` — doesn't block response | **+2-5s latency** per tool query. User waits for memory extraction before getting response. |
| **7** | **Dynamic `response_format` detection** | `client.py:221-230` | Uses `litellm.get_supported_openai_params()` to check if model supports JSON mode | **JSON mode fails silently** for models that don't support it → garbled output. |
| **8** | **Context window enforcement** | `client.py:240-245** | Counts tokens before LLM call, caps `max_tokens` to 80% of remaining budget | **Context overflow errors** for long sessions. LLM calls fail with token limit exceeded. |
| **9** | **Milestone reducer for messages** | `state.py:25-38` | Keeps only last 10 messages + milestone-tagged ones. Prevents O(N²) growth. | **Unbounded message growth**. Every turn adds to prompt → each call gets slower. Eventually hits context window. |
| **10** | **Tool cache with 60s TTL** | `runner.py:78-86` | Caches all tool definitions from DB, refreshes every 60s instead of per-request | **+100-500ms** per request from DB query. No impact on accuracy. |
| **11** | **Embedding text hash cache** | `registry.py:419-428** | Caches embedding vectors by text hash in Redis (TTL 1h) | **+200-1000ms** per cache-miss query. Duplicate queries re-compute embeddings. |
| **12** | **Skip LLM rerank at high confidence** | `discovery.py:53-59** | Skips LLM rerank when top-1 cosine similarity > 0.9 | **+500-2000ms** when top result is already correct. Unnecessary LLM call. |
| **13** | **Affinity graph multi-tool tracking** | `tool_executor.py:350-358** | Records all DAG task names for co-occurrence learning | **Tool affinity graph learns nothing**. Can't recommend get_geocoding before get_weather. |
| **14** | **Dynamic prompt depth** | `understand_intent.py:110-118** | Uses short prompt for simple queries, full thinking protocol for complex ones | **Simple queries get slower** (full thinking protocol always used). Complex queries stay correct. |
| **15** | **DB connection cleanup (async with)** | `runner.py:225`, `discover_tools.py:48`, `tool_executor.py:388` | Wraps DB sessions in `async with` context managers | **Connection pool exhaustion** after 6 concurrent requests. "QueuePool limit exceeded" errors. |

## LLM Call Counts Per Query Type

| Query Type | Before Optimizations | After Optimizations |
|---|---|---|
| Greeting ("Hi") | 2 calls (understand_intent + respond) | **0 calls** (template-based) |
| Single-tool ("Tell me a joke") | 5 calls (understand + discover + plan + finalize + reflect) | **2 calls** (understand + finalize) |
| Meta ("What tools?") | 1 call (understand_intent) | **1 call** (understand_intent, instant template) |
| Complex multi-tool | 5 calls | **3 calls** (understand + plan + finalize) |

## Prompts (7 registered)

| Prompt File | Version | Used By |
|-------------|---------|---------|
| `understand_intent.py` | v4.0-simple / v4.0-complex | `understand_intent` node — dynamically selected by query complexity |
| `plan_parallel.py` | v1.0 | `dag_expander` node |
| `reflect_on_response.py` | v1.0 | `reflect_on_response` node |
| `finalize.py` | v3.0 | `finalize` node |
| `gather_requirements.py` | v2.0 | `gather_requirements` node |
| `execute_step.py` | v2.0 | Legacy — unused in active graph but kept for reference |
| `analyze_results.py` | v3.0 | Legacy — unused in active graph but kept for reference |
| `plan.py` | v3.0 | Legacy — unused in active graph but kept for reference |

## Dependencies

- `nexus/llm/` — LLMClient for all model calls
- `nexus/tools/` — ToolRegistry, ToolExecutor, DynamicToolSelector
- `nexus/sessions/` — SessionService for message persistence
- `nexus/memory/` — MemoryManager, PostgresSaver checkpointer
- `nexus/redis_client/` — EventBus for streaming agent events
