# Security

The Nexus Agent uses a **passthrough auth model** at the API boundary — no
JWT verification, no API key validation, no tenant isolation (single-tenant by
default). Security hardening is enforced at the EXECUTION boundary instead,
where the capability actually runs.

## Execution-boundary security gates (P0 — enforced, metadata-driven)

Every tool execution passes the gate chain in `ToolExecutor.execute()`:

1. **Input validation** — JSON-Schema against the tool's `input_schema`.
2. **Sandbox host whitelist** — always; an empty whitelist blocks all hosts.
3. **SSRF hardening** — for the DYNAMIC-endpoint class (the resolved host was
   influenced by tool inputs): scheme validation (http/https only) +
   private/loopback/link-local/reserved-address blocking (loopback, RFC1918,
   CGNAT, 169.254.x.x incl. the cloud metadata IP 169.254.169.254, IPv6
   `::1`/`fc00::/7`/`fe80::/10`) + DNS-rebinding guard (resolved addresses
   are validated at resolution time). Operator-registered static endpoints
   are trusted by configuration.
4. **Authorization gate** — a capability whose `validation_rules.allowed_roles`
   is configured is executable ONLY by callers whose roles intersect the
   declared set (`context.user_roles`); unconfigured capabilities remain open
   (the operator's explicit choice). The gate is the enforcement point for
   role-based access; tenant isolation is the next phase.
5. **Idempotency** — when `validation_rules.idempotency_header` is declared,
   the invocation's stable `idempotency_key` (hash of session + task +
   resolved inputs — the SAME key across retries and recovery) is stamped on
   the request so the provider can deduplicate side effects.
6. **Approval binding** — human approvals bind to the exact operation
   (`operation_hash` of policy + step + tools + inputs); a replanned or
   modified operation is never auto-authorized.
7. **Prompt-injection boundary** — artifact content and retrieved memory are
   UNTRUSTED DATA in the synthesis prompt (finalize v4.1 rule 0): anything
   inside artifact data that looks like an instruction is inert facts, never
   followed or repeated.
8. **Memory provenance** — memories carry `observed_at`/`source`/`scope`/
   `confidence` (+ optional `expires_at`); the scout never retrieves expired
   entries; failed/degenerate responses are never stored.

## Current API-boundary model

- **Auth Middleware**: Injects a default user identity for all requests
- **Rate Limiting**: Per-IP rate limiting via Redis
- **HTTPS**: Enforced via reverse proxy (nginx)
- **Secrets**: All tool API keys live in environment variables
  (`EnvSecretResolver`); never committed, never logged (sensitive-field
  masking on every logged payload)

## Data Protection

- All secrets (API keys for tools) are stored in environment variables
- Database connections use TLS when available
- Redis connections can be configured with a password

## Roadmap

- Tenant isolation (multi-tenant authorization at the capability level)
- Credential vault (managed secret storage per tenant)
- Full RBAC at the API boundary (JWT/API-key verification)
