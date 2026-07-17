"""Locust load test for Nexus Agent.

Simulates 100 concurrent chat sessions across 5 tenants with a mix of
simple (70%) and complex (30%) flows.

Usage:
    locust -f tests/load/locustfile.py --host=http://localhost:8000
    # or headless:
    locust -f tests/load/locustfile.py --headless -u 100 -r 10 --run-time 5m \\
        --host=http://localhost:8000 --csv=results/load_test
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from locust import HttpUser, between, events, task

from tests.load.complex_flow import make_complex_session
from tests.load.simple_flow import make_simple_session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TENANTS = [str(uuid.uuid4()) for _ in range(5)]


def _pick_tenant() -> str:
    return TENANTS[int(time.monotonic()) % len(TENANTS)]


# ---------------------------------------------------------------------------
# Event hooks for custom statistics
# ---------------------------------------------------------------------------


@events.init.add_listener
def on_locust_init(environment, **_kwargs):
    """Register custom statistics tracked during the test."""
    environment.stats.total = 0
    environment.stats.simple_latencies = []
    environment.stats.complex_latencies = []
    environment.stats.ttft_values = []


@events.quitting.add_listener
def on_locust_quit(environment, **_kwargs):
    """Print summary report on exit."""
    latencies = getattr(environment.stats, "simple_latencies", [])
    if latencies:
        latencies.sort()
        n = len(latencies)
        logger.info("=== Simple Flow Latency (ms) ===")
        logger.info(
            "  p50: %.1f  p95: %.1f  p99: %.1f",
            latencies[n // 2],
            latencies[int(n * 0.95)],
            latencies[int(n * 0.99)],
        )
    latencies = getattr(environment.stats, "complex_latencies", [])
    if latencies:
        latencies.sort()
        n = len(latencies)
        logger.info("=== Complex Flow Latency (ms) ===")
        logger.info(
            "  p50: %.1f  p95: %.1f  p99: %.1f",
            latencies[n // 2],
            latencies[int(n * 0.95)],
            latencies[int(n * 0.99)],
        )
    ttft = getattr(environment.stats, "ttft_values", [])
    if ttft:
        ttft.sort()
        n = len(ttft)
        logger.info("=== TTFT (ms) ===")
        logger.info(
            "  p50: %.1f  p95: %.1f  p99: %.1f",
            ttft[n // 2],
            ttft[int(n * 0.95)],
            ttft[int(n * 0.99)],
        )


# ---------------------------------------------------------------------------
# Locust user
# ---------------------------------------------------------------------------


class NexusAgentUser(HttpUser):
    """Simulates a user sending chat messages and consuming SSE events."""

    wait_time = between(1, 3)
    host = "http://localhost:8000"

    @task(7)
    def simple_chat(self):
        self._run_flow("simple", make_simple_session)

    @task(3)
    def complex_chat(self):
        self._run_flow("complex", make_complex_session)

    def _run_flow(self, flow_type: str, session_factory):
        tenant_id = _pick_tenant()
        session_data = session_factory(tenant_id)
        session_id = session_data["session_id"]
        start = time.monotonic()

        try:
            with self.client.stream(
                "POST",
                f"/api/v1/sessions/{session_id}/chat",
                json={"message": session_data["message"], "stream": True},
                headers={
                    "X-Tenant-ID": tenant_id,
                    "Content-Type": "application/json",
                },
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"Unexpected status {response.status_code}")
                    return

                first_event = True
                event_count = 0
                tool_calls = 0
                errors = []

                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        event_count += 1
                        try:
                            payload = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        if first_event:
                            env = self.environment
                            env.stats.ttft_values.append((time.monotonic() - start) * 1000)
                            first_event = False

                        event_type = payload.get("type", "")
                        if event_type == "tool_call_started":
                            tool_calls += 1
                        elif event_type == "error":
                            errors.append(payload.get("payload", {}).get("message", "unknown"))

                duration_ms = (time.monotonic() - start) * 1000
                success = not errors

                if flow_type == "simple":
                    env.stats.simple_latencies.append(duration_ms)
                else:
                    env.stats.complex_latencies.append(duration_ms)

                if success:
                    response.success()
                else:
                    response.failure(f"Errors: {errors}")

                logger.info(
                    "flow=%s session=%s duration=%.0fms events=%d tools=%d errors=%d",
                    flow_type,
                    session_id,
                    duration_ms,
                    event_count,
                    tool_calls,
                    len(errors),
                )

        except Exception as exc:
            logger.warning("flow=%s session=%s failed: %s", flow_type, session_id, exc)
