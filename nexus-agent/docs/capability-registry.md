# Capability Registry & Runtime Resolution

## Overview

The Capability Registry is the backbone of late-binding tool resolution.
Every tool/API in the system is represented as a **capability** (what it does),
with one or more **providers** (who offers it), and **endpoints** (how to call it).

Two complementary resolution layers exist:

1. **Retrieval-first (candidate selection)** — `capabilities/retrieval.py`
   narrows the catalog BEFORE planning: BM25 corpus built from prebuilt
   `search_doc` (name, aliases, capabilities, category, tags, keywords,
   produces/consumes, related, description, purpose, examples), alias
   exact/token-containment, and an example/keyword boost with dynamic
   generic-token demotion. Top-K (15) candidates reach the planner.
2. **Operation resolution (compile time)** — `capabilities/resolution.py`
   maps a chosen logical op to the best endpoint: L1 exact → L2 domain →
   L3 alias (exact + token, NFKD-normalized) → L4 RapidFuzz ≥ threshold →
   L5 LLM repair (top-K). Never guesses below threshold; unresolved ops are
   dropped with explicit `errors[]`.

**Registry sync** — registering/updating/deleting a tool (API or SDK)
persists the row, then **syncs capability/provider/endpoint rows**, commits,
refreshes GlobalContext indexes (aliases/domains/keywords/search docs), and
bumps the persisted (Redis) cache marker so cached plans invalidate. The
runtime resolves capabilities via the registry, not the tool table.

> **Roadmap:** Phase 1 consolidates retrieval into a single `ResolutionEngine`
> producing one frozen `ResolutionResult` (ranked candidates + availability
> facts + match reasons) consumed by router, planner, and telemetry.

## Resolver

File: `src/nexus/capabilities/resolution.py`

The resolver provides ranked-candidate resolution from the
`CompiledCapabilityGraph`. Each candidate carries metadata so the executor
can fall back to alternatives on validation failure.

All weights are configurable via `settings.resolver` (``CapabilityResolverSettings``).

| Factor | Default Weight | Description |
|--------|---------------|-------------|
| Capability Match | 2.0 | Exact logical_op_name match (always 1.0 — enforced by instructor) |
| Schema Match | 1.5 | Input key overlap with capability's `consumes` |
| Reliability | 1.5 | EWMA reliability score from ProviderModel (0.0–1.0) |
| Latency | 1.0 | Normalized inversely to latency_p99_ms |
| Cost | 1.0 | Normalized inversely to cost_per_call |
| Permissions | 2.0 | Whether user context satisfies required_permissions |
| User Preference | 0.5 | Exact match on preferred_provider name |
| Version | 0.5 | Semantic version recency |
| Deprecation | ×0.5 multiplier | Deprecated endpoints penalized after sum |

### CandidateEndpoint Model

```python
class CandidateEndpoint(BaseModel):
    endpoint_id: str
    capability: str
    provider_name: str
    url: str
    http_method: str
    score: float
    cost_per_call: float
    latency_p99_ms: int | None
    reliability_score: float
    api_version: str | None
    deprecated: bool
    min_tier: str | None
```

## SchemaMatcher

File: `src/nexus/capabilities/schema_matcher.py`

Compares the endpoint's declared `consumes` (from CapabilityModel) against
the caller's actual input keys. Returns a score in [0.0, 1.0]:

- 1.0: all required keys present
- 0.5: partial overlap (or no consumes declared)
- 0.0: no overlap

## Candidate Ranking Pass

File: `src/nexus/compiler/passes/pass_candidate_ranking.py`

Pure optimization pass that enriches every ``ToolNode`` in the
``ExecutionGraph`` with a deduplicated `candidate_endpoints` list.
The primary endpoint is always at position 0; alternatives from the
resolver follow.

## Late-Binding Fallback in Executor

File: `src/nexus/agent/executors/concurrent_executor.py:_execute_single`

When a tool execution returns `validation_error` or a contract failure,
the executor pops the next candidate from the task's `candidate_endpoints`
list and retries with a different URL/method — no LLM re-entry required.

## New EndpointModel Columns (Migration `b2c3d4e5f6a7`)

| Column | Type | Purpose |
|--------|------|---------|
| `required_permissions` | JSONB | List of permissions needed to call this endpoint |
| `api_version` | String(50) | API version (e.g. "2.1") for version-aware scoring |
| `deprecated` | Boolean | Whether this endpoint is deprecated |
| `min_tier` | String(50) | Minimum user tier required |

## Settings Reference

```env
# Dynamic Capability Resolver
NEXUS_RESOLVER__CAPABILITY_MATCH_WEIGHT=2.0
NEXUS_RESOLVER__SCHEMA_MATCH_WEIGHT=1.5
NEXUS_RESOLVER__RELIABILITY_WEIGHT=1.5
NEXUS_RESOLVER__LATENCY_WEIGHT=1.0
NEXUS_RESOLVER__COST_WEIGHT=1.0
NEXUS_RESOLVER__PERMISSIONS_WEIGHT=2.0
NEXUS_RESOLVER__USER_PREFERENCE_WEIGHT=0.5
NEXUS_RESOLVER__VERSION_WEIGHT=0.5
NEXUS_RESOLVER__DEPRECATED_PENALTY=0.5
NEXUS_RESOLVER__MAX_LATENCY_MS=5000
NEXUS_RESOLVER__MAX_COST_USD=1.0
NEXUS_RESOLVER__DEFAULT_RELIABILITY=0.8
NEXUS_RESOLVER__TOP_K_CANDIDATES=3
```

## Test Coverage

Run with: `uv run pytest tests/test_dynamic_resolver_scoring.py -v`

Contains 9 tests:
- 5 SchemaMatcher tests (exact, partial, no overlap, empty, no consumes)
- 4 CandidateRankingPass tests (primary endpoint, merge, dedup, MapNode body)
