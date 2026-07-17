# `src/nexus/agent/` — LangGraph Orchestration

This module owns the LangGraph StateGraph that implements a hybrid ReAct + Plan-and-Execute reasoning loop. The agent contains **zero business logic** — it plans, reasons, gathers requirements, and invokes tools.

## Key Responsibilities

- Define `StateGraph` topology with 9 nodes (understand_intent → gather_requirements → discover_tools → plan → select_and_bind_tools → execute_step → analyze_results → present_preview → finalize).
- Manage graph lifecycle: compile with checkpointer, stream updates, cache per session.
- Provide `AgentRunner` that wires LLM, tools, memory, event bus, and session lock.
- Human-in-the-Loop via LangGraph `interrupt()` for approvals and feedback.
- Supervisor + sub-agent patterns reserved for future `StateGroup` / subgraphs.

## Key Files

| File | Responsibility |
|------|---------------|
| `graph.py` | `build_agent_graph()` — constructs, wires dependencies, compiles `StateGraph` with conditional edges and max-iteration guard |
| `runner.py` | `AgentRunner` — session-scoped graph cache, `invoke()` async generator streaming `AgentEvent` types, Redis distributed lock to prevent concurrent runs |
| `state.py` | `AgentState` TypedDict (messages, plan, tool_results, pending_approval, etc.), `PlanStep`, `Plan`, `IntentAnalysis`, `AnalysisResult`, `MissingSlot` Pydantic models |
| `hitl.py` | `interrupt_for_approval()` with 5 criteria (tool flag, destructiveness, risk level, global default, name patterns), `build_approval_payload()` |
| `hitl_middleware.py` | Wraps `ToolExecutor` to intercept calls requiring HITL approval |
| `feedback_interrupt.py` | `interrupt_for_feedback()` for intermediate preview approval (approve/edit/reject) |
| `api.py` | FastAPI router `/agent` — invoke, stream (SSE), resume, approve/reject/edit, get state |
| `errors.py` | Re-exports agent-specific exceptions from central error module |
| `schemas.py` | Request/response models: `AgentInvokeRequest`, `AgentStreamEvent`, `ApprovalAction`, etc. |
| `graph_cache.py` | In-memory cache for compiled graphs per session |

## Nodes (`nodes/`)

| Node | File | Behaviour |
|------|------|-----------|
| understand_intent | `understand_intent.py` | LLM extracts `IntentAnalysis` with primary_goal, missing_info_slots, confidence; routes to clarification if confidence < 0.5 |
| gather_requirements | `gather_requirements.py` | Generates at most 3 clarifying questions per turn referencing missing slots; merges answers into `gathered_requirements` |
| discover_tools | `discover_tools.py` | Calls `DynamicToolSelector` to populate `available_tools` via semantic search + optional LLM re-rank |
| plan | `plan.py` | LLM structured output `Plan` with steps, rationale, destructive flag; flags plan as needs_human_review if destructive |
| select_and_bind_tools | `select_and_bind_tools.py` | Pre-filters tools for current plan step, converts to OpenAI tool-call schema |
| execute_step | `execute_step.py` | ReAct micro-loop: resolves `${...}` placeholders, validates inputs, calls `ToolExecutor` (HITL-aware), error recovery (retry/revise/ask) |
| analyze_results | `analyze_results.py` | LLM evaluates outcome vs expected_outcome; routes to continue/revise/clarify/escalate/finalize |
| present_preview | `present_preview.py` | Interrupts for human feedback on intermediate results; supports approve/edit/reject with plan rollback |
| finalize | `finalize.py` | Composes final answer with tool citations, persists episodic memory via `MemoryManager` |

## Prompts (`prompts/`)

| File | Content |
|------|---------|
| `manager.py` | `PromptManager` — versioned prompt templates with A/B testing weights, `render()` |
| `understand_intent.py` | v1.0 + v2.0 with 6 few-shot examples |
| `gather_requirements.py` | Clarifying question generation prompt |
| `plan.py` | Step-by-step plan generation prompt |
| `execute_step.py` | ReAct loop prompt |
| `analyze_results.py` | Outcome evaluation prompt |
| `finalize.py` | Final answer composition prompt |

## Dependencies

- `nexus/llm/` — LLMClient for all model calls
- `nexus/tools/` — ToolRegistry, ToolExecutor, DynamicToolSelector
- `nexus/sessions/` — SessionService for message persistence
- `nexus/memory/` — MemoryManager, PostgresSaver checkpointer
- `nexus/redis_client/` — EventBus for streaming agent events
