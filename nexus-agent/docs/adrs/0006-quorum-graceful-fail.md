# ADR-006 — Quorum Failure Is a Decision, Not an Exception

- **Status:** Accepted
- **Date:** 2026-08-07

## Context
`ReflectionNode` raised `QuorumFailureError` when more than the quorum
threshold of tasks failed — an exception bypassed the entire recovery
layer and aborted the run, even when usable artifacts existed.

## Decision
Quorum failure now returns a graceful FAIL decision: compensation runs
(best-effort), `_recovery_failed_tasks` is recorded, the graph routes to
`ResponseNode`, and any surviving artifacts are rendered. The
`QuorumFailureError` class was removed.

## Consequences
- A successful execution can never abort the run.
- Failures always flow through the recovery layer to a user response.
