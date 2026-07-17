# Incident Runbook

Common incidents, diagnostic queries, and recovery procedures for the Nexus Agent platform.

---

## Incident Index

| # | Incident | Severity | Page |
|---|----------|----------|------|
| 1 | LLM Provider Outage | Critical | [↓](#1-llm-provider-outage) |
| 2 | Database Connection Exhaustion | Critical | [↓](#2-database-connection-exhaustion) |
| 3 | Stuck Agent Run | High | [↓](#3-stuck-agent-run) |
| 4 | Runaway Cost | High | [↓](#4-runaway-cost) |
| 5 | Tool Endpoint Down | Medium | [↓](#5-tool-endpoint-down) |
| 6 | Redis Out of Memory | Medium | [↓](#6-redis-out-of-memory) |
| 7 | HITL Approval Stalled | Medium | [↓](#7-hitl-approval-stalled) |
| 8 | Agent Hangs in Revise Loop | Medium | [↓](#8-agent-hangs-in-revise-loop) |
| 9 | SSE Connection Leak | Medium | [↓](#9-sse-connection-leak) |
| 10 | Checkpoint / Memory Growth | Low | [↓](#10-checkpoint--memory-growth) |
| 11 | Pod CrashLoopBackOff (K8s) | Critical | [↓](#11-pod-crashloopbackoff-k8s) |

---

## 1. LLM Provider Outage

**Symptoms:**
- Agent returns `"Service degraded"` messages
- `/metrics` shows `llm_cost_usd_total` flat
- `CircuitBreakerRegistry.is_open(provider)` returns `True`

**Diagnostic queries:**

```bash
# Check circuit breaker state
uv run python -c "
from nexus.errors.circuit_breaker import CircuitBreakerRegistry
print(CircuitBreakerRegistry.get_instance().get_all_states())
"

# Check recent LLM errors in logs
grep "llm.call.failed" server.log | tail -20
```

**Recovery:**
1. Identify which provider is down from circuit breaker state
2. Configure fallback provider: `NEXUS_LLM__DEFAULT_MODEL=gpt-4o-mini`
3. If all providers down, the agent returns cached responses via `DegradationManager`
4. Restart provider service or rotate API key
5. Reset circuit breaker: `CircuitBreakerRegistry.get_instance().reset(provider_name)`

---

## 2. Database Connection Exhaustion

**Symptoms:**
- Slow requests, `TimeoutError` from DB operations
- `/readyz` may report `database: error` or succeed slowly
- Application logs show `sqlalchemy.exc.TimeoutError`

**Diagnostic queries:**

```bash
# Active connections
uv run python -c "
import asyncio, asyncpg
async def check():
    conn = await asyncpg.connect('postgresql://nexus:pass@localhost:5433/nexus')
    rows = await conn.fetch('SELECT count(*) FROM pg_stat_activity WHERE datname=\\'nexus\\'')
    await conn.close()
    print(f'Active connections: {rows[0][0]}')
asyncio.run(check())
"

# Long-running queries (>30s)
psql -h localhost -p 5433 -U nexus -d nexus -c "
SELECT pid, now() - query_start AS duration, state, query
FROM pg_stat_activity
WHERE state = 'active' AND now() - query_start > interval '30 seconds'
ORDER BY duration DESC;
"
```

**Recovery:**
1. Kill long-running queries:
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE state = 'active' AND now() - query_start > interval '30 seconds';
   ```
2. Increase pool: `NEXUS_DATABASE__POOL_SIZE=20 NEXUS_DATABASE__MAX_OVERFLOW=40`
3. Add PgBouncer for connection pooling in production
4. Investigate query patterns — look for missing indexes or N+1 queries

---

## 3. Stuck Agent Run

**Symptoms:**
- SSE stream hangs mid-response
- `agent_run` table shows `status='running'` for >5 minutes
- No `final_response` event delivered

**Diagnostic queries:**

```sql
-- Find stuck runs
SELECT id, session_id, tenant_id, started_at,
       now() - started_at AS duration
FROM agent_run
WHERE status = 'running'
  AND started_at < now() - interval '5 minutes'
ORDER BY started_at;

-- Check checkpointer state
SELECT thread_id, checkpoint_id, created_at
FROM checkpoints
WHERE thread_id IN (
    SELECT session_id::text FROM agent_run
    WHERE status = 'running' AND started_at < now() - interval '5 min'
);
```

**Recovery:**
1. Cancel the stuck run via API:
   ```bash
   curl -X POST http://localhost:8000/api/v1/agent/{session_id}/cancel \
     -H "X-Tenant-ID: <tenant_id>"
   ```
2. If API unavailable, force-update the DB:
   ```sql
   UPDATE agent_run SET status = 'interrupted', ended_at = now()
   WHERE status = 'running' AND started_at < now() - interval '5 minutes';
   ```
3. Release Redis locks:
   ```bash
   redis-cli KEYS "lock:agent_run:*" | xargs redis-cli DEL
   ```
4. Investigate root cause: check logs for the specific session_id

---

## 4. Runaway Cost

**Symptoms:**
- Cost dashboard shows >2x normal daily spend
- Alert fires from `CostAlertService` at 80% / 100% thresholds
- LLM cost metrics spike

**Diagnostic queries:**

```bash
# Top spenders today
uv run python -c "
import asyncio, asyncpg
async def check():
    conn = await asyncpg.connect('postgresql://nexus:pass@localhost:5433/nexus')
    rows = await conn.fetch('''
        SELECT tenant_id, sum(total_cost_usd) AS cost, count(*) AS runs
        FROM agent_run
        WHERE started_at > now() - interval '1 day'
        GROUP BY tenant_id ORDER BY cost DESC LIMIT 10
    ''')
    for r in rows: print(f'  {r[tenant_id]}: \${r[cost]:.2f} ({r[runs]} runs)')
    await conn.close()
asyncio.run(check())
"

# Most expensive single runs
psql -h localhost -p 5433 -U nexus -d nexus -c "
SELECT id, tenant_id, total_cost_usd, total_tokens, started_at
FROM agent_run
WHERE started_at > now() - interval '1 day'
ORDER BY total_cost_usd DESC LIMIT 10;
"
```

**Recovery:**
1. Enable cost cap: verify `NEXUS_AGENT__COST_CAP_ENABLED=true`
2. Manually degrade tenant model:
   ```bash
   redis-cli SET "cost_degraded:<tenant_id>" "gpt-4o-mini" EX 86400
   ```
3. Block offending tenant:
   ```sql
   UPDATE tenant SET status = 'suspended' WHERE id = '<tenant_id>';
   ```
4. Investigate which tools or patterns caused high token usage

---

## 5. Tool Endpoint Down

**Symptoms:**
- `tool_execution` rows with `status='error'` for a specific tool
- Agent reports "I was unable to complete that action"
- Tool owner reports API outage

**Diagnostic queries:**

```sql
-- Find failing tools
SELECT tool_id, t.name, count(*) AS failures,
       min(te.created_at) AS first_failure,
       max(te.created_at) AS last_failure
FROM tool_execution te
JOIN tool t ON t.id = te.tool_id
WHERE te.status = 'error'
  AND te.created_at > now() - interval '1 hour'
GROUP BY tool_id, t.name
ORDER BY failures DESC;

-- Check circuit breaker state
SELECT id, name, enabled
FROM tool
WHERE enabled = true AND id IN (
    SELECT tool_id FROM tool_execution
    WHERE status = 'error' AND created_at > now() - interval '5 min'
);
```

**Recovery:**
1. Disable the failing tool:
   ```bash
   curl -X DELETE http://localhost:8000/api/v1/tools/{tool_id} \
     -H "X-Tenant-ID: <tenant_id>"
   ```
2. Alert tool owner to investigate their API
3. If tool recovery expected soon, leave enabled — circuit breaker will auto-recover
4. For critical tools, configure a fallback tool or cached response

---

## 6. Redis Out of Memory

**Symptoms:**
- `docker compose logs redis` shows `OOM command not allowed when used memory > 'maxmemory'`
- Redis starts evicting keys (cache miss rate increases)
- Rate limiting / pub/sub / locks may fail silently

**Diagnostic commands:**

```bash
# Check memory usage
docker compose exec redis redis-cli info memory | grep -E "used_memory_human|maxmemory_human|evicted_keys"

# List largest keys
docker compose exec redis redis-cli --bigkeys

# Check hit rate
docker compose exec redis redis-cli info stats | grep keyspace_hits
```

**Recovery:**
1. Flush cache (acceptable — cache is ephemeral):
   ```bash
   docker compose exec redis redis-cli FLUSHDB
   ```
2. Increase Redis maxmemory in `docker-compose.yml`:
   ```yaml
   redis:
     command: redis-server --maxmemory 2gb --maxmemory-policy allkeys-lru
   ```
3. Add `--maxmemory-policy allkeys-lru` to prevent hard OOM failures
4. If persistent, reduce cache TTLs in settings

---

## 7. HITL Approval Stalled

**Symptoms:**
- `hitl_approvals_pending` gauge > 50
- Users report "waiting for approval" for hours
- SSE events show `approval_required` but no decision

**Diagnostic queries:**

```sql
-- Pending approvals older than 1 hour
SELECT a.id, a.agent_run_id, a.tool_call->>'tool_name' AS tool,
       a.created_at, now() - a.created_at AS age
FROM approval a
JOIN agent_run ar ON ar.id = a.agent_run_id
WHERE a.status = 'pending'
  AND a.created_at < now() - interval '1 hour'
ORDER BY a.created_at;

-- Check approval timeout setting
SHOW approval_timeout_hours;
```

**Recovery:**
1. Auto-reject expired approvals (configurable timeout, default 24h):
   ```sql
   UPDATE approval SET status = 'rejected',
     decision_payload = '{"auto_rejected": true, "reason": "timeout"}'
   WHERE status = 'pending' AND created_at < now() - interval '24 hours';
   ```
2. Reduce timeout: `NEXUS_AGENT__APPROVAL_TIMEOUT_HOURS=1`
3. Manually approve/reject via API:
   ```bash
   curl -X POST http://localhost:8000/api/v1/approvals/{id}/decide \
     -H "Content-Type: application/json" \
     -d '{"action": "approve"}'
   ```
4. Add Slack/email notification for pending approvals (see `CostAlertService` as template)

---

## 8. Agent Hangs in Revise Loop

**Symptoms:**
- Same plan step executes repeatedly
- `iteration_count` in `agent_run.graph_state` keeps incrementing
- No progress toward tool execution

**Diagnostic queries:**

```bash
# Check iteration count from graph state
psql -h localhost -p 5433 -U nexus -d nexus -c "
SELECT id, session_id, graph_state->>'iteration_count' AS iterations,
       started_at, now() - started_at AS duration
FROM agent_run
WHERE status = 'running'
  AND (graph_state->>'iteration_count')::int > 5
ORDER BY started_at;
"
```

**Recovery:**
1. Cancel the run (see [Stuck Agent Run](#3-stuck-agent-run))
2. Reduce max iterations: `NEXUS_AGENT__MAX_ITERATIONS=5`
3. Check plan quality — poor plans cause repeated revise cycles
4. If systemic, tighten tool descriptions to reduce LLM confusion

---

## 9. SSE Connection Leak

**Symptoms:**
- `active_sessions` metric steadily increases without corresponding decrease
- Container memory grows over time
- Load balancer reports connection count higher than expected

**Diagnostic commands:**

```bash
# Check active SSE connections in app
curl -s http://localhost:8000/readyz | jq .

# Count open connections to app
netstat -an | grep :8000 | grep ESTABLISHED | wc -l

# Check Redis pub/sub channels
redis-cli PUBSUB CHANNELS "agent_events:*" | wc -l
```

**Recovery:**
1. Drain connections: trigger `SIGTERM` — drain middleware closes SSE connections
2. Restart the pod after drain timeout (30s)
3. Ensure clients implement `EventSource.close()` on navigation/unload
4. Consider WebSocket with ping/pong as alternative

---

## 10. Checkpoint / Memory Growth

**Symptoms:**
- `checkpoints` table grows unbounded
- Slow checkpoint reads over time (LangGraph state loading)
- DB disk usage increases steadily

**Diagnostic queries:**

```sql
-- Checkpoint table size
SELECT pg_size_pretty(pg_total_relation_size('checkpoints')) AS size;

-- Count by thread
SELECT thread_id, count(*) AS versions
FROM checkpoints
GROUP BY thread_id
ORDER BY versions DESC LIMIT 20;

-- Memory table size
SELECT pg_size_pretty(pg_total_relation_size('memory')) AS size,
       pg_size_pretty(pg_total_relation_size('memory_embedding_idx')) AS index_size;
```

**Recovery:**
1. Archive old checkpoints (keep last 30 days):
   ```sql
   DELETE FROM checkpoints WHERE created_at < now() - interval '30 days';
   ```
2. Vacuum: `VACUUM ANALYZE checkpoints;`
3. Configure checkpoint TTL in LangGraph settings
4. Run `MemoryManager.decay()` to archive low-importance memories

---

## 11. Pod CrashLoopBackOff (K8s)

**Symptoms:**
- `kubectl get pods` shows `CrashLoopBackOff` or `Unhealthy`
- Pod restarts repeatedly

**Diagnostic commands:**

```bash
# Check logs from previous (failed) instance
kubectl logs <pod-name> --previous

# Check probe configuration
kubectl describe pod <pod-name> | grep -A 10 "Liveness\|Readiness"

# Check if dependencies are available
kubectl get endpoints postgres redis
```

**Recovery:**
1. Ensure dependent services are healthy first (PostgreSQL, Redis)
2. If `/readyz` fails for dependencies, the pod will not receive traffic — fix dependencies
3. If probes are too aggressive, adjust `failureThreshold` and `periodSeconds`
4. If OOM-killed, increase memory limits: `resources.limits.memory: 1Gi`

---

## Diagnostic Reference

### Fast diagnostic queries (copy-paste ready)

```sql
-- All running agent runs older than 5 minutes
SELECT id, session_id, tenant_id, started_at,
       now() - started_at AS age
FROM agent_run
WHERE status = 'running' AND started_at < now() - interval '5 min';

-- Top 10 slowest tools today
SELECT t.name, avg(te.duration_ms)::int AS avg_ms,
       count(*) AS calls, max(te.duration_ms) AS max_ms
FROM tool_execution te
JOIN tool t ON t.id = te.tool_id
WHERE te.created_at > now() - interval '1 day'
GROUP BY t.name ORDER BY avg_ms DESC LIMIT 10;

-- Top 10 most expensive sessions today
SELECT session_id, tenant_id, sum(total_cost_usd) AS cost,
       count(*) AS runs
FROM agent_run
WHERE started_at > now() - interval '1 day'
GROUP BY session_id, tenant_id
ORDER BY cost DESC LIMIT 10;

-- Tools with error rate > 10%
SELECT t.name, count(*) AS total,
       sum(CASE WHEN te.status != 'success' THEN 1 ELSE 0 END) AS errors,
       round(100.0 * sum(CASE WHEN te.status != 'success' THEN 1 ELSE 0 END) / count(*), 1) AS error_pct
FROM tool_execution te
JOIN tool t ON t.id = te.tool_id
WHERE te.created_at > now() - interval '1 day'
GROUP BY t.name
HAVING count(*) > 10
   AND 100.0 * sum(CASE WHEN te.status != 'success' THEN 1 ELSE 0 END) / count(*) > 10
ORDER BY error_pct DESC;

-- Redis cache hit rate
INFO stats | grep keyspace_hits

-- DB connection count
SELECT count(*) FROM pg_stat_activity WHERE datname = 'nexus';
```
