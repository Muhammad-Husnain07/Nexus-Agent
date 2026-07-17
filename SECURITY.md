# Security Model

This document describes the Nexus Agent security model, assumed attack vectors, and mitigations.

---

## Architecture Overview

```
Client ──→ FastAPI Gateway ──→ AuthN/Z ──→ Agent Graph ──→ Tool Executor ──→ External APIs
                 │                │                         │
                 ↓                ↓                         ↓
           Tenant Isolation    RBAC + JWT/ApiKey       Credential Vault
```

---

## Attack Vectors & Mitigations

| Vector | Mitigation | Implementation |
|--------|-----------|---------------|
| Prompt injection | Input guard scans user messages for injection patterns | `PromptInjectionGuard` in `src/nexus/security/input_guard.py` |
| SSRF via tool endpoints | Sandbox whitelists allowed hosts | `SandboxConfig.allowed_hosts` in `src/nexus/tools/sandbox.py` |
| JWT tampering | RS256/HS256 validation via python-jose | `verify_jwt()` in `src/nexus/security/auth.py` |
| Timing attacks on API keys | Constant-time comparison via argon2 | `verify_api_key()` in `src/nexus/security/auth.py` |
| Credential theft | AES-256-GCM encryption at rest, master key from env/Vault | `ToolCredentialVault` in `src/nexus/security/credentials.py` |
| Cross-tenant data access | `tenant_id` on every row, TenantQuery mixin auto-filters | `TenantMixin` + repositories in `src/nexus/db/` |
| Rate limiting bypass | Tiered rate limits: per-IP, per-tenant, per-user, per-session | `TieredRateLimitMiddleware` in `src/nexus/security/rate_limit.py` |
| Leaked secrets in logs | Sensitive field masking (Authorization, api_key) | `mask_sensitive_fields()` in `src/nexus/tools/sandbox.py` |
| Unauthorized tool registration | RBAC: only tenant_admin/developer can register tools | `require_permission(Permission.REGISTER_TOOLS)` |
| LLM tool misuse | HITL approval gate before destructive/risky tool calls | `ApprovalRequiredInterrupt` in `src/nexus/tools/approval_gate.py` |
| Dependency vulnerabilities | `pip-audit` in CI, `bandit` in pre-commit | CI security job, `.pre-commit-config.yaml` |
| Secret leak via git | `detect-private-key` hook, `.gitignore` | Pre-commit hook |
| CSRF | FastAPI CORS middleware with explicit origins | `CORSMiddleware` in `api/main.py` |
| Clickjacking | `X-Frame-Options: DENY` | Security headers middleware in `api/main.py` |
| MITM | `Strict-Transport-Security` header | Security headers middleware in `api/main.py` |

---

## Authentication Flow

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐
│  Client   │────→│  AuthMiddleware  │────→│  RBAC Check   │
└──────────┘     └──────────────┘     └──────────────┘
                       │
          ┌────────────┼────────────┐
          ↓            ↓            ↓
     Bearer JWT    X-API-Key    X-Tenant-ID
     (python-jose) (argon2)    (tenant lookup)
```

---

## Pen-Test Notes

### Prompt Injection
The agent's system prompt instructs it to follow tool descriptions precisely. An attacker might attempt:
- `"Ignore previous instructions and ..."`
- `"You are now a different AI ..."`
- Hidden unicode characters, zero-width spaces

**Mitigation**: `PromptInjectionGuard` scans for known patterns and flags them. The agent is instructed to never override tool input/output schemas based on user content.

### SSRF via Tool Endpoints
If `sandbox_enabled=true` (default), only hosts in `allowed_hosts` are reachable. Test:
- `http://169.254.169.254/latest/meta-data/` (AWS metadata)
- `http://localhost:5432/` (internal services)
- DNS rebinding attacks

**Mitigation**: Host whitelist, no wildcard subdomain patterns.

### DoS via Tool Execution
A user could craft a prompt that asks the agent to call many tools in sequence.

**Mitigation**: `NEXUS_AGENT__MAX_ITERATIONS` (default 10), `NEXUS_AGENT__MAX_PLAN_STEPS` (default 5), per-tool timeout.

### Credential Extraction
If an attacker gains database access, they could read `encrypted_blob` from `tool_credential` table.

**Mitigation**: AES-256-GCM with master key from environment variable. The master key is never stored in the database.

---

## Vulnerability Reporting

Report security vulnerabilities to the Nexus Agent team by opening a GitHub Issue with the label `security`. Do not disclose vulnerabilities publicly until they are resolved.

---

## Compliance Checklist

- [x] Data at rest encryption (credential vault)
- [x] Data in transit encryption (HTTPS in production)
- [x] Input validation (JSON Schema for tool inputs)
- [x] Output sanitization (`OutputGuard` for agent responses)
- [x] Authentication (JWT + API key)
- [x] Authorization (RBAC with 4 roles, 14 permissions)
- [x] Audit logging (all privileged actions logged)
- [x] Rate limiting (tiered, per-tenant)
- [x] Secrets management (environment variables / Vault)
- [x] Dependency scanning (`pip-audit` in CI)
- [ ] Penetration test (external — recommended before production launch)
