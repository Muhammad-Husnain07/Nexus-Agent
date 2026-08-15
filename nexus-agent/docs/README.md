# Nexus Agent — Documentation

Index of all documentation for the **Nexus Agent Orchestration Runtime**.

## Architecture Status (FROZEN)

The orchestration architecture (P0-A resolver → P2-A hierarchical mega-DAG
planning) is validated and frozen. Production model config: Nemotron-3-Ultra
for planner + synthesis, embeddings OFF. Benchmark: 98/135 × 3 reproducible
(mean 91.1), binding 1.0. See [roadmap.md](roadmap.md) for the full phase
ledger and [invariants.md](invariants.md) for I1–I19.

## Architecture & Design

| Doc | Purpose |
|-----|---------|
| [engineering-principles.md](engineering-principles.md) | **The binding rulebook** — 25 principles + anti-patterns for production LangGraph agents (read before ANY code) |
| [architecture.md](architecture.md) | Current runtime architecture: intent → plan → validator → compiler → executor, typed contracts, infra |
| [runtime-contract.md](runtime-contract.md) | **Architectural guardrails** — invariants, typed contracts, side-effect rules (read first) |
| [roadmap.md](roadmap.md) | Phase ledger + completed phases (P0 → P2-A, model A/B, benchmark baselines) |

## ADRs (Architecture Decision Records)

| Doc | Decision |
|-----|----------|
| [adrs/0001-single-canonical-graph.md](adrs/0001-single-canonical-graph.md) | Single canonical execution graph |
| [adrs/0002-typed-status-recovery.md](adrs/0002-typed-status-recovery.md) | Typed-status recovery state machine |
| [adrs/0003-artifact-first-response.md](adrs/0003-artifact-first-response.md) | Response only claims what artifacts prove |
| [adrs/0004-versioned-cache-keys.md](adrs/0004-versioned-cache-keys.md) | Versioned cache keys |
| [adrs/0005-node-contract-registry.md](adrs/0005-node-contract-registry.md) | Node contracts + drift tests |
| [adrs/0006-quorum-graceful-fail.md](adrs/0006-quorum-graceful-fail.md) | Quorum failure is graceful, never raised |
| [adrs/0007-architecture-baseline.md](adrs/0007-architecture-baseline.md) | The frozen baseline + handoff/P4/P0 amendments |
| [adrs/0008-architecture-versioning.md](adrs/0008-architecture-versioning.md) | The version manifest — single cache-key fingerprint |

## Capabilities & Tools

| Doc | Purpose |
|-----|---------|
| [tool-registration.md](tool-registration.md) | Registering HTTP/MCP tools — full field reference, schemas, validation rules |
| [capability-registry.md](capability-registry.md) | Retrieval-first resolution, registry sync, enrichment metadata, resolution layers |
| [mcp.md](mcp.md) | MCP server surface (`/mcp`) |

## Platform Guides

| Doc | Purpose |
|-----|---------|
| [integration-guide.md](integration-guide.md) | Integrating the runtime into your application (Python SDK, chat API, events) |
| [embedding.md](embedding.md) | Embedding the assistant (widget studio, embed scripts, preview) |
| [frontend-guide.md](frontend-guide.md) | Frontend console development (React/TanStack Query/Zustand conventions) |
| [api-reference.md](api-reference.md) | REST endpoint reference (`/api/v1/…`) |
| [memory.md](memory.md) | Memory architecture (checkpointer, long-term store, MemoryScout) |
| [hitl.md](hitl.md) | Conversational human-in-the-loop approvals (semantic-bound) |

## Operations

| Doc | Purpose |
|-----|---------|
| [operations.md](operations.md) | Deployment (Docker/WSL2), scaling, backups, monitoring |
| [runbook.md](runbook.md) | Incident runbook — symptoms, diagnostics, recovery |
| [performance.md](performance.md) | Performance budgets and SLOs |

---

## Quick orientation

1. Read **[engineering-principles.md](engineering-principles.md)** — the binding rulebook.
2. Read **[runtime-contract.md](runtime-contract.md)** — it governs all code.
3. Read **[architecture.md](architecture.md)** for how the runtime is wired.
4. Check **[roadmap.md](roadmap.md)** to see what is being built next.
5. See the **[ADRs](adrs/)** for the architectural decisions (0001–0008).
