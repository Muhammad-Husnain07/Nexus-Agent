# ADR-005 — Node Contract Registry (code-enforced)

- **Status:** Accepted
- **Date:** 2026-08-07

## Context
Node responsibilities drifted (dead nodes, unconsumed outputs, undeclared
state writes). Documentation alone cannot prevent architectural drift.

## Decision
1. `src/nexus/agent/contracts.py` — one frozen `NodeContract` per graph
   node: phase (compile/runtime/routing), inputs/reads/writes (single
   ownership), produces/consumes, may_fail, skip_if, recovery,
   output_consumed_by.
2. `tests/test_node_contracts.py` — static verification: AST extraction of
   actual state writes per node module/function, two-way check against the
   declared contract, single-ownership, producer coverage, phase isolation,
   output consumption, graph liveness, plus the execution invariants
   (success+artifacts ⇒ never error; response reads only artifacts;
   optimizer returns new graph objects).

## Consequences
- Architectural drift fails CI before it corrupts behavior.
- The registry is the single source of truth for node responsibilities.
