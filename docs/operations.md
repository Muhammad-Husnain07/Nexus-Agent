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

### PostgreSQL + pgvector

```bash
# Daily backup
pg_dump -h localhost -p 5433 -U nexus -d nexus -F c -f nexus_backup_$(date +%Y%m%d).dump

# Restore
pg_restore -h localhost -p 5433 -U nexus -d nexus -F c nexus_backup_20260717.dump

# With WAL archiving for point-in-time recovery
# Enable in postgresql.conf: archive_mode=on, archive_command='cp %p /backups/%f'
```

### Automated Backup Strategy

| Data | Frequency | Retention | Tool |
|------|-----------|-----------|------|
| Database | Hourly | 24 hours | pg_dump / WAL-G |
| Database | Daily | 30 days | pg_dump / WAL-G |
| Database | Monthly | 1 year | pg_dump / WAL-G |
| Config (.env, k8s) | Per change | Git history | git |

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

### Incident: LLM Provider Down

**Symptoms:** Agent returns `"Service degraded"`, `/metrics` shows `llm_cost_usd_total` flat.

**Steps:**
1. Check `DegradationManager.check_llm_available()` — returns `False`
2. Identify which provider: check circuit breaker states via logs
3. Configure fallback provider in env: `NEXUS_LLM__DEFAULT_MODEL=gpt-4o-mini`
4. If all providers down, the agent returns cached responses or degradation message
5. **Fix:** Restart provider or swap API key

### Incident: Redis Disconnected

**Symptoms:** `/readyz` shows `redis: error`, rate limiting disabled, caching disabled.

**Steps:**
1. Check Redis container: `docker compose ps redis`
2. Check logs: `docker compose logs redis`
3. If Redis is down and cannot restart, the app continues working (cache miss, rate limiting bypassed)
4. **Fix:** `docker compose restart redis`
5. If persistent, check Redis RAM: `docker compose exec redis redis-cli info memory`

### Incident: DB Pool Exhausted

**Symptoms:** Slow requests, `TimeoutError` from DB operations, `/readyz` may still report OK.

**Steps:**
1. Check active connections: `SELECT count(*) FROM pg_stat_activity WHERE datname = 'nexus'`
2. Increase pool: edit `NEXUS_DATABASE__POOL_SIZE` and restart
3. Kill long-running queries: 
   ```sql
   SELECT pg_terminate_backend(pid) 
   FROM pg_stat_activity 
   WHERE state = 'active' AND now() - query_start > interval '30 seconds';
   ```
4. **Fix:** Optimise query patterns, increase pool size, add connection pooling (PgBouncer)

### Incident: High Approval Latency

**Symptoms:** Users complaining about slow responses, `hitl_approvals_pending` gauge > 50.

**Steps:**
1. Check pending approvals: `GET /api/v1/approvals/pending/{session_id}`
2. Check `approval_timeout_hours` setting (default 24h)
3. If too many pending, reduce timeout: `NEXUS_AGENT__APPROVAL_TIMEOUT_HOURS=1`
4. **Fix:** Implement auto-approve for low-risk tools, add Slack notification for pending approvals

### Incident: Memory Growing

**Symptoms:** Container OOM-killed, memory graph shows steady increase.

**Steps:**
1. Check checkpoint table: `SELECT count(*) FROM checkpoints`
2. LangGraph checkpoints grow with conversation history
3. Run VACUUM: `VACUUM ANALYZE checkpoints;`
4. **Fix:** Configure checkpoint TTL or periodic cleanup job

### Incident: Unhealthy Pod (Kubernetes)

**Symptoms:** `kubectl get pods` shows `CrashLoopBackOff` or `Unhealthy`.

**Steps:**
1. Check logs: `kubectl logs <pod-name> --previous`
2. Check probes match readiness: failureThreshold may need adjustment
3. If `/readyz` fails for dependencies (PG/Redis down), the pod will not receive traffic
4. **Fix:** Ensure dependencies are healthy first, then `kubectl delete pod <pod-name>`
