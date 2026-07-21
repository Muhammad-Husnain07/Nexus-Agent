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

## Prompts (7 registered)

| Prompt File | Version | Used By |
|-------------|---------|---------|
| `understand_intent.py` | v3.0 | `understand_intent` node |
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
