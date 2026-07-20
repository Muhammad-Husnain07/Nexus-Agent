# `src/nexus/security/` — Authorization & Rate Limiting

## Key Responsibilities

- Passthrough auth middleware (injects default user identity, no JWT verification).
- Tiered rate limiting per endpoint prefix via Redis.
- No RBAC, no scopes, no credential encryption.
