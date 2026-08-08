# `src/nexus/security/` — Authorization & Rate Limiting

> **Runtime Contract** (binding): see [`docs/runtime-contract.md`](../../../docs/runtime-contract.md).
> Policies are metadata, not logic — approval/risk decisions come from
> capability metadata, never hardcoded tool names.

## Key Responsibilities

- Passthrough auth middleware (injects default user identity, no JWT verification).
- Tiered rate limiting per endpoint prefix via Redis.
- No RBAC, no scopes, no credential encryption.
