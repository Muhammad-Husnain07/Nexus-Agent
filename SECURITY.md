# Security

The Nexus Agent uses a **passthrough auth model** — no JWT verification, no API key validation, no RBAC enforcement.

## Current Security Model

- **Auth Middleware**: Injects a default user identity for all requests
- **Tenant Middleware**: Single-tenant — injects a fixed tenant ID
- **Rate Limiting**: Per-endpoint rate limiting via Redis (tiered)
- **HTTPS**: Enforced via reverse proxy (nginx)

## Outbound Tool Calls

Tool HTTP calls support standard auth headers:
- Bearer tokens
- Basic auth
- Custom headers

These are configured per tool in the tool registry.

## Data Protection

- All secrets (API keys for tools) are stored in environment variables
- Database connections use TLS when available
- Redis connections can be configured with a password
