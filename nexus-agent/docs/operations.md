# Operations Guide

Deployment, scaling, backups, monitoring, and common incident runbook.

---

## Deployment

### Docker Compose (Development / Small-Scale)

```bash
# Start the full stack
docker compose -f docker/docker-compose.yml up -d

# With optional services (after uncommenting in compose file)
docker compose -f docker/docker-compose.yml up -d --profile monitoring

# View logs
docker compose logs -f nexus-agent

# Graceful shutdown
docker compose down
```

### Docker Compose (Dev Mode — Hot Reload)

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.override.yml up -d
```

### Kubernetes (Production)

```bash
# Apply all manifests
kubectl apply -f deploy/k8s/

# Check rollout status
kubectl rollout status deployment/nexus-agent

# Scale manually
kubectl scale deployment/nexus-agent --replicas=5

# View logs
kubectl logs -l app=nexus-agent
```

See [deploy/k8s/](../deploy/k8s/) for all manifests:
- `deployment.yaml` — 2 replicas, non-root, probes, 30s grace period
- `hpa.yaml` — autoscaling (CPU 70%, custom sessions metric)
- `pdb.yaml` — max 1 unavailable during rolling updates
- `network-policy.yaml` — ingress from nginx + prometheus only
- `configmap.yaml` — all non-secret configuration
- `secret.yaml` — credentials (externalise via ExternalSecrets/Vault)

---

## JWT Secret Management

The JWT signing secret (`NEXUS_AUTH__JWT_SECRET`) must NEVER be stored in
`.env.example` or committed to git. In production, set it via a secret manager
(HashiCorp Vault, AWS Secrets Manager, GitHub Actions secrets) and inject it
as an environment variable.

Generate a strong secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

The application will refuse to start if the secret is empty, is the literal
string ``change-me``, or is shorter than 32 characters.

---

## Scaling

### Horizontal Scaling (Kubernetes)

| Resource | Recommendation |
|----------|---------------|
| Min replicas | 2 (HA) |
| Max replicas | 10 (CPU or active_sessions driven) |
| CPU request | 250m |
| Memory request | 512Mi |
| Memory limit | 1Gi |
| HPA metric | CPU at 70% target utilization |
| Custom metric | `active_sessions` at 100 avg per pod |

### Connection Pools

| Service | Setting | Default | Production Tuning |
|---------|---------|---------|-------------------|
| PostgreSQL | `pool_size` | 10 | `replicas * 5` |
| PostgreSQL | `max_overflow` | 20 | `replicas * 10` |
| Redis | `max_connections` | 20 | `replicas * 10` |
| Tool client | `max_keepalive_connections` | 20 | 50 |
| Tool client | `max_connections` | 100 | 200 |

---

## Backups

Use the provided scripts for consistent backup and restore operations:

```bash
# Create a timestamped backup
DATABASE_URL="postgresql://nexus:pass@localhost:5433/nexus" ./scripts/backup.sh

# Restore from a backup (with --confirm flag)
DATABASE_URL="postgresql://nexus:pass@localhost:5433/nexus" ./scripts/restore.sh /path/to/backup.dump --confirm
```

### Automated Backup Strategy

| Data | Frequency | Retention | Tool |
|------|-----------|-----------|------|
| Database | Hourly | 24 hours | `scripts/backup.sh` via cron |
| Database | Daily | 30 days | `scripts/backup.sh` via cron |
| Database | Monthly | 1 year | S3 lifecycle policy |
| Config (.env, k8s) | Per change | Git history | git |

### RPO / RTO

| Metric | Target |
|--------|--------|
| Recovery Point Objective (RPO) | 1 hour (hourly backup schedule) |
| Recovery Time Objective (RTO) | 30 minutes for 10 GB database |

---

## Monitoring

### Health Endpoints

| Endpoint | Purpose | Expected |
|----------|---------|----------|
| `GET /healthz` | Liveness probe | `{"status":"ok"}` |
| `GET /readyz` | Readiness + dependencies | `{"status":"ok","database":"ok","redis":"ok"}` |
| `GET /metrics` | Prometheus scrape | Prometheus text format |

### Prometheus Metrics

| Metric | Type | Labels |
|--------|------|--------|
| `agent_runs_total` | Counter | `tenant`, `status` |
| `agent_run_duration_seconds` | Histogram | `tenant` |
| `tool_calls_total` | Counter | `tenant`, `tool`, `status` |
| `llm_tokens_total` | Counter | `tenant`, `provider`, `direction` |
| `llm_cost_usd_total` | Counter | `tenant` |
| `active_sessions` | Gauge | `tenant` |
| `hitl_approvals_pending` | Gauge | `tenant` |

### Alert Thresholds

| Alert | Condition | Severity |
|-------|-----------|----------|
| High error rate | 5xx responses > 5% in 5 min | Critical |
| High latency | p99 response time > 5s | Critical |
| Redis disconnected | `/readyz` shows Redis error | Warning |
| DB pool exhausted | Pool waiting > 10 connections | Warning |
| High cost spend | Daily cost > threshold | Warning |
| Pending approvals > 50 | `hitl_approvals_pending` > 50 | Warning |

### Tracing (OpenTelemetry)

Configure the collector endpoint via `NEXUS_OBSERVABILITY__OTEL_ENDPOINT`. Auto-instrumented:
- HTTPX tool calls
- asyncpg queries
- Redis operations
- FastAPI request spans

### LLM Tracing (LangSmith)

Enable via:
```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=nexus-agent
```

---

## Runbook

See the [Incident Runbook](runbook.md) for complete incident procedures covering:
- LLM Provider Outage
- Database Connection Exhaustion
- Stuck Agent Run
- Runaway Cost
- Tool Endpoint Down
- Redis Out of Memory
- HITL Approval Stalled
- Agent Revise Loop
- SSE Connection Leak
- Checkpoint / Memory Growth
- Pod CrashLoopBackOff
