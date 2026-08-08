# Engineering Principles — Binding Rules for Production LangGraph Agents

> **Binding.** These rules govern ALL code written for this repository. A
> LangGraph agent is a **distributed workflow engine with LLM-assisted
> decision-making**, not "an LLM with tools." The LLM proposes plans and
> generates language; deterministic components enforce correctness, validate
> plans, manage state, execute tools, recover from failures, and maintain
> system invariants. That separation is what makes the agent reliable,
> scalable, and maintainable in production.

## 1. Architecture

- Define clear node responsibilities (Single Responsibility Principle).
- Nodes should be deterministic where possible.
- Separate planning, execution, memory, and response generation.
- Keep orchestration independent of business logic.
- Use immutable execution plans.
- Avoid hidden side effects between nodes.
- Prefer composition over giant nodes.
- Design for extensibility from day one.

## 2. State Management

- Keep state minimal.
- Separate persistent state from ephemeral state.
- Never mutate shared objects in place.
- Version state schemas.
- Validate state after every node.
- Remove stale fields.
- Prevent state drift.
- Use typed state models.

## 3. Planner

The planner is usually the weakest component. Be careful about: multi-intent
decomposition, dependency detection, missing steps, extra invented steps,
parameter extraction, negation, comparisons, sequential workflows, parallel
workflows, follow-up questions, context resolution, empty-plan handling,
plan repair, planner confidence. **Never trust the first plan. Always
validate it.**

## 4. Plan Validation

Validate before execution: missing producer, missing consumer, cycles,
invalid dependencies, unknown capability, duplicate nodes, empty workflow,
intent coverage, extraneous operations, parameter completeness, budget
violations. **Never execute an invalid plan.**

## 5. Capability Registry

Treat the registry as the source of truth. Each capability declares: id,
aliases, keywords, description, produces, consumes, required inputs, optional
inputs, output schema, retry policy, timeout, cacheability, permissions,
side effects, cost, latency estimate. **Never hardcode capability logic.**

## 6. Capability Resolution

Use layered resolution (exact → alias → keyword → semantic → fuzzy → LLM
repair). Always return confidence scores.

## 7. Tool Execution

Every tool supports: timeout, retry, cancellation, idempotency, fallback,
structured errors, validation, observability. **Never assume tools succeed.**

## 8. Artifact System

Treat artifacts as typed objects: schema version, provenance, execution id,
timestamps, producing capability, normalized payload. **Never pass raw API
responses everywhere. Normalize once.**

## 9. Context Management

Never dump everything into the prompt. Build a context compiler selecting
only relevant artifacts, recent history, memory, retrieved documents,
execution summaries. Budget every token.

## 10. Memory

Separate memory types (working, conversation, long-term, artifact,
preferences, summaries). **Never store failed responses. Deduplicate
memories.**

## 11. Prompt Engineering

Prompts have one job (router, planner, response synthesis). Avoid prompts
doing multiple unrelated tasks. Version prompts. A/B test prompts.

## 12. Response Generation

Never answer directly from raw tool JSON. Pipeline: Tool → Normalize →
Artifact → Renderer → LLM polish. Always have a deterministic fallback.

## 13. Recovery

Have recovery at every layer: retry, alternative capability, cache, partial
response, clarification, graceful failure. **Never fail silently.**

## 14. Error Handling

Errors are typed (ValidationError, PlanningError, ToolError, TimeoutError,
PermissionError, DependencyError). **Never rely on string matching.**

## 15. Observability

Measure everything: planner latency, executor latency, node latency, retries,
cache hits, planner repairs, token usage, tool latency, response latency,
failures. **Without metrics, optimization is guesswork.**

## 16. Caching

Different caches serve different purposes (prompt, parse, plan, execution,
artifact, retrieval, embedding). **Version cache keys.**

## 17. Graph Design

Support: sequential, parallel, fan-out/fan-in, conditional branches, loops,
map-reduce, supervisor-worker, planner-executor, event-driven,
human-in-the-loop, checkpoint & resume, rollback.

## 18. Concurrency

Be careful with: race conditions, duplicate execution, shared state,
ordering, locks, cancellation, resource limits.

## 19. Contracts

Every node has explicit contracts: inputs, outputs, invariants, ownership,
side effects, failure modes. Test contract drift automatically.

## 20. Versioning

Version independently: prompts, node contracts, artifacts, execution graph,
normalizer, renderer, orchestration API, state schema. **Never mix
incompatible versions.** (See `src/nexus/agent/architecture.py` — the single
architecture manifest, ADR 0008.)

## 21. Testing

Multiple layers: unit, node, planner, validator, tool mocks, integration,
end-to-end, live tool tests, regression suites, scenario matrix, performance
benchmarks, fuzz testing.

## 22. Security

Protect against: prompt injection, tool injection, secret leakage, unsafe
tool execution, SSRF, command injection, excessive permissions, untrusted
outputs.

## 23. Human Experience

Ask clarification only when necessary. Explain failures honestly. Show
progress for long tasks. Return partial results when possible. **Never
fabricate missing information.** Preserve conversational continuity.

## 24. Performance

Optimize based on measurements, not assumptions. Track: planning time,
execution time, memory time, synthesis time, cache hit rate, token usage,
parallelism efficiency.

## 25. Long-Term Maintainability

Plugin architecture, capability discovery, dependency injection, feature
flags, configuration over code, ADRs, immutable interfaces, backward
compatibility, automated migration tests, comprehensive documentation.

## Common Anti-Patterns to Avoid

- One giant planner prompt doing everything.
- Hardcoded tool routing.
- Passing raw tool outputs directly to the LLM.
- Mutable shared state across nodes.
- Planner output executed without validation.
- No deterministic fallback when the LLM fails.
- Silent error handling.
- Unbounded conversation history.
- Mixing orchestration with business logic.
- Storing failed or hallucinated responses in memory.
- Optimizing before collecting metrics.
- Depending solely on the LLM instead of deterministic validation.

## Golden Rule

Treat a LangGraph agent as a **distributed workflow engine with
LLM-assisted decision-making**, not as "an LLM with tools."
