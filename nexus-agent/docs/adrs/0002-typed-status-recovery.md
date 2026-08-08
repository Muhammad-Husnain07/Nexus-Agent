# ADR-002 — Typed-Status Recovery Classification

- **Status:** Accepted
- **Date:** 2026-08-07

## Context
`RecoveryManager` classified failures by substring-matching error TEXT
(``"unavailable"``, ``"not found"``, …) — a pattern list that drifted from
the producers and could misclassify.

## Decision
Producers emit TYPED statuses; recovery classifies on status only:
- transient: `timeout`, `rate_limited`, HTTP 5xx
- hard structural: `unavailable` (tripped circuit), `tool_not_found`
- contract: `validation_error`
- post-execution validation failures join the typed set from
  `_validation_failed`

## Consequences
- No text-pattern matching anywhere in recovery.
- Classification is deterministic and producer-driven.
