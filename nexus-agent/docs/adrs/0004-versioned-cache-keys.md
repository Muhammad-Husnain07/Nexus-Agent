# ADR-004 — Versioned Cache Keys

- **Status:** Accepted
- **Date:** 2026-08-07

## Context
Caches were keyed by content + registry fingerprint only. A code change to
the compiler or artifact schema could serve stale compiled plans.

## Decision
Every cache key includes the producer versions:
- ParseCache: `query + model + context + COMPILER_VERSION +
  ARTIFACT_SCHEMA_VERSION + registry fingerprint`
- PlanCache (compiled graphs): `logical-workflow hash + COMPILER_VERSION +
  ARTIFACT_SCHEMA_VERSION + registry fingerprint`
- Artifact dedup: `artifact_type + canonical content_hash + schema_version`
  (normalized payload only — never raw JSON)

## Consequences
- Deployment-safe invalidation: old code can never serve stale plans.
- Artifact memories dedup across repeated cache hits.
