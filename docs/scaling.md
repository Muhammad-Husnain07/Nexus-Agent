# Scaling Validation

Horizontal scaling characteristics and validation for the Nexus Agent platform.

---

## Architecture Model

Nexus Agent is **stateless at the application layer**. All durable state lives in PostgreSQL and Redis:

| State | Storage | Horizontally Scalable |
|-------|---------|----------------------|
| Conversation messages | PostgreSQL (`message` table) | ✅ Yes |
| Session state | PostgreSQL (`session` table) | ✅ Yes |
| Agent graph state (checkpoints) | PostgreSQL (`checkpoints` table via LangGraph `PostgresSaver`) | ✅ Yes |
| Long-term memory | PostgreSQL (`memory` table with pgvector) | ✅ Yes |
| Tool registry | PostgreSQL (`tool` table) | ✅ Yes |
| Tool executions | PostgreSQL (`tool_execution` table) | ✅ Yes |
| LLM response cache | Redis | ✅ Yes (Redis cluster) |
| Rate limiting counters | Redis | ✅ Yes (Redis cluster) |
| Pub/sub fan-out | Redis | ✅ Yes (Redis cluster) |
| Agent run locks | Redis | ✅ Yes (Redis cluster) |
| Cost degradation flags | Redis | ✅ Yes (Redis cluster) |
| In-memory graph cache | Process-local (`graph_cache.py`) | ⚠️ Per-process, disposable |

---

## Multi-Instance Safety

### Checkpointer (`PostgresSaver`)
- Uses `psycopg` async connection pool — safe under concurrent access
- LangGraph checkpoints use PostgreSQL row-level locking for thread-safe writes
- Each app instance reads/writes the same `checkpoints` table
- **Verdict**: Safe for N instances

### Memory Store (`MemoryStore`)
- All operations go through SQLAlchemy ORM with `AsyncSession`
- No local caching — every read hits PostgreSQL
- **Verdict**: Safe for N instances

### Agent Runner Lock
- Redis `SET NX EX` distributed lock prevents concurrent runs on the same session
- Lock key: `lock:agent_run:{session_id}`
- Lua-based atomic release prevents race conditions
- **Verdict**: Safe for N instances

### Pub/Sub Fan-Out
- Redis pub/sub channels: `agent_events:{session_id}`, `tool_events:{session_id}`
- WebSocket handler subscribes per session, broadcasts to all connected clients
- Multiple app instances: each instance has its own Redis pub/sub subscription
- SSE responses go directly to the instance handling the HTTP request
- **Verdict**: Safe — clients pinned to one instance via sticky session or reconnect

### In-Memory Graph Cache
- `AgentRunner._graphs` is a per-instance dict mapping session_id → compiled `StateGraph`
- If an instance restarts or a request goes to a different instance, the graph is rebuilt
- LangGraph `PostgresSaver` loads checkpoint state from the database
- **Verdict**: Safe — cache miss only causes a ~100ms graph rebuild

---

## Horizontal Scaling Guidelines

| Resource | Recommendation |
|----------|---------------|
| Min replicas | 2 (HA) |
| Max replicas | 10 (CPU or active_sessions driven) |
| CPU request | 250m |
| Memory request | 512Mi |
| Memory limit | 1Gi |
| HPA metric | CPU at 70% target utilization |
| Custom metric | `active_sessions` at 100 avg per pod |

### Connection Pool Sizing

Formula: `pool = replicas * 5`, `overflow = replicas * 10`

| Instances | PG pool_size | PG max_overflow | Redis max_connections |
|-----------|-------------|-----------------|----------------------|
| 2 | 10 | 20 | 20 |
| 5 | 25 | 50 | 50 |
| 10 | 50 | 100 | 100 |

---

## Scaling Test Procedure

```bash
# 1. Start stack with 3 app instances
docker compose up -d --scale nexus-agent=3

# 2. Run load test
locust -f tests/load/locustfile.py --headless -u 100 -r 10 \
  --run-time 10m --host=http://localhost:8000

# 3. Verify no state leakage
# - Check that sessions created on instance A are accessible from instance B
# - Check that checkpoints written on instance B are readable from instance C
# - Verify memory extraction is independent of instance

# 4. Check no duplicate events
# - Verify SSE delivers each event exactly once
# - Check Redis pub/sub has correct subscriber count

# 5. Monitor connection pools
curl -s http://localhost:8000/readyz
```

---

## Known Limitations

1. **In-memory graph cache**: On instance restart or deploy, the first request to a session incurs graph rebuild overhead (~100ms). Acceptable for HA deployments.
2. **SSE connection affinity**: SSE connections are pinned to the instance that handled the chat request. A deploy during an active SSE stream will disconnect the client. Clients should reconnect with existing `session_id` to resume.
3. **Checkpoint table growth**: Without TTL cleanup, the `checkpoints` table grows unbounded. Run periodic cleanup (see runbook.md §10).
