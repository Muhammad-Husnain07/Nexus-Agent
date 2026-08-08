# ADR-003 — Artifact-First Response Synthesis

- **Status:** Accepted
- **Date:** 2026-08-07

## Context
A successful execution could surface as a user-facing error when the
finalize LLM failed or produced degenerate output — successful artifacts
were discarded.

## Decision
1. `ResponseNode` consumes ONLY the ArtifactGraph (never raw tool results).
2. When synthesis fails or stays degenerate AND artifacts exist, the
   pluggable `RendererRegistry` renders them deterministically.
3. A successful execution + artifacts can NEVER yield
   `response_type="error"` — the `_synthesis_failed` flag records the
   degraded path instead.
4. Workflow artifact passthrough renders real artifacts (never the generic
   "Artifact generated successfully.").

## Consequences
- Successful data is never lost to a formatter failure.
- Invariant is enforced by `tests/test_node_contracts.py`.
