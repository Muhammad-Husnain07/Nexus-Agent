# ADR-001 — Single Canonical Execution Graph

- **Status:** Accepted
- **Date:** 2026-08-07

## Context
The state once carried `_execution_graph` and `_optimized_graph` — two
near-identical graph copies. Readers used `_optimized_graph or
_execution_graph` fallbacks, so the second copy was pure checkpoint weight.

## Decision
One canonical graph: `_execution_graph`. The optimizer REPLACES it in place
(via a fresh immutable model instance) and records pass deltas in
`_optimization_snapshots` + a monotonic `_graph_version`. `_optimized_graph`
was removed entirely.

## Consequences
- Checkpoint payloads shrink; no dual-source drift possible.
- `_graph_version` + snapshots give immutable version history by reference.
