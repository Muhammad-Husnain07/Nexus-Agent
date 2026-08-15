# Performance Budgets

Service-level objectives for the Nexus Agent platform. All budgets must be verified before each release via load testing.

---

## Budgets

| Metric | Budget | Measurement Point | Priority |
|--------|--------|-------------------|----------|
| p95 first-token latency | **< 2s** | SSE `token` event vs request start time | Critical |
| p95 tool call overhead | **< 500ms** | `ToolExecutor.execute()` minus external HTTP call duration | High |
| p95 SSE event gap | **< 1s** | Time between consecutive SSE `data:` lines in same stream | High |
| p95 end-to-end simple chat | **< 5s** | Request start to `final_response` event (1-tool flow) | Medium |
| p99 DB query time | **< 200ms** | asyncpg query duration (OpenTelemetry span) | Medium |
| Redis operations per request | **< 20** | Count of Redis commands per agent turn | Low |
| Memory per idle connection | **< 50MB RSS** | Per uvicorn worker at idle, measured via `ps` | Low |

---

## Measurement Methodology

### First-Token Latency (TTFT)
```python
# Measured in locustfile.py
start = time.monotonic()
for line in response.iter_lines():
    if line.startswith("data: "):
        ttft = (time.monotonic() - start) * 1000  # ms
        break
```

### Tool Call Overhead
Measured as `ToolExecutor.execute()` total duration minus the external HTTP request round-trip:
```
overhead = total_duration - external_http_duration
```
Includes: input validation, auth resolution, sandbox check, output validation, persistence, event publishing.

### SSE Event Gap
```python
# Measured as max interval between consecutive SSE events in a stream
gaps = []
prev_ts = None
for line in stream:
    if line.startswith("data: "):
        now = time.monotonic()
        if prev_ts:
            gaps.append(now - prev_ts)
        prev_ts = now
```

---

## Verification

Run the load test suite before each release:

```bash
# Start infrastructure with 3 app instances
docker compose up -d --scale nexus-agent=3

# Run 5-minute load test targeting performance budgets
locust -f tests/load/locustfile.py --headless -u 100 -r 10 \
  --run-time 5m --host=http://localhost:8000 --csv=results/perf_test

# Check results
python -c "
import csv
with open('results/perf_test_stats.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['Name'] == 'POST /api/v1/sessions/{id}/chat':
            print(f\"p50: {row['50%']}ms  p95: {row['95%']}ms  p99: {row['99%']}ms\")
"
```

---

## Degradation Plan

If budgets are not met:

| Budget Miss | Action |
|-------------|--------|
| TTFT > 2s | Reduce LLM model size, enable response caching, increase app replicas |
| Tool overhead > 500ms | Profile `ToolExecutor`, optimize schema validation, add connection pooling |
| SSE gap > 1s | Check LLM streaming throughput, reduce tool payload sizes |
| DB query > 200ms | Add missing indexes, optimize N+1 queries, increase PG pool |

---

## Orchestration Benchmark (135-scenario matrix)

`scripts/run_benchmark.py` scores 135 scenarios across 10 dimensions (intent,
resolution, binding, topology, parallelism, artifacts, recovery, validation,
grounding, efficiency) with failure-class classification, intent accounting,
wave timing (critical-path), synthesis-coverage breakdown, and
`BENCHMARK_CONTRACT` classification for structurally-impossible expectations.

### Baselines (frozen architecture)

| Run | Config | Pass | Avg | Notes |
|---|---|---|---|---|
| Run 13 | Nano+Nano | 94/135 | 90.3 | Nano planner empty-plan class |
| Run 14 | Nano+Ultra | 95/135 | 89.7 | 5 llm_failed (Ultra endpoint under load) |
| **135×3** | **Ultra+Ultra** | **98/135 × 3** | **91.1** | reproducible; binding 1.0; artifacts 0.788; grounding 0.763; topology 0.975 |

### Mega-DAG validation (P2-A)

T132/U133/W135 (20-30 intent requests): chunked hierarchical planning
eliminates the `got []` empty-plan class. On clean reps: 0 empty plans, 100%
expected-kind coverage, 0 invented ops, 0 dangling maps, 0 unnecessary
replans, binding 1.0, execution starts 3/3 (T132 3/3 stable). The remaining
variability is NIM endpoint latency (decomposer timeouts → `detected=0`),
cleanly separated from orchestration.

### P2-A.5 planning critical path (W135)

```
chunk planning (4 parallel):  78.4s wall  (per-chunk 18/23/35/78s)
merge + coverage recovery:   ~0.1s
planner total:               78.7s
execution:                   begins (9+ graph steps), budget-limited
```

Parallel chunk extraction ⇒ planning wall = **max(chunk)** (78.4s), not the
154s sum. Chunk imbalance (18→78s variance) is the identified optimization
target for the separate P3 experiment.

### Failure taxonomy (post-freeze)

| Class | Count | Cause |
|---|---|---|
| ARTIFACT_GRAPH synthesis omissions | ~28-33 | Class B: available=required, rendered<required — Nemotron generation omission (Ultra residual; measurable via coverage_breakdown) |
| Weather+geocode strict contract | ~6 | BENCHMARK_CONTRACT (weather requires lat/lon; geocode plan is correct) |
| Docker BINDING | ~3 | Genuinely unresolvable `repository` input (honest BINDING_FAILED) |
| Ultra endpoint timeouts | variable | NIM `detected=0` under sustained load (not orchestration) |
