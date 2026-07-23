"""PerformanceTracker — tool latency, error rate tracking, and degradation detection.

Collects per-call metrics with a sliding window, computes composite scores
for ranking, and detects degrading tools via circuit-breaker patterns.
"""

from __future__ import annotations

import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.tools.performance")


class ToolPerformanceMetrics:
    """Sliding-window performance metrics for a single tool."""

    def __init__(self, tool_id: str, window_minutes: int = 60) -> None:
        self.tool_id = tool_id
        self.window = timedelta(minutes=window_minutes)
        self._records: list[dict[str, Any]] = []

    def record(self, latency_ms: float, success: bool, error_type: str | None = None) -> None:
        """Add a call record and trim the sliding window."""
        now = datetime.now(UTC)
        self._records.append({
            "latency_ms": latency_ms,
            "success": success,
            "error_type": error_type,
            "timestamp": now,
        })
        cutoff = now - self.window
        self._records = [r for r in self._records if r["timestamp"] > cutoff]

    @property
    def total_calls(self) -> int:
        return len(self._records)

    @property
    def success_rate(self) -> float:
        if not self._records:
            return 1.0
        successes = sum(1 for r in self._records if r["success"])
        return successes / len(self._records)

    @property
    def avg_latency_ms(self) -> float:
        if not self._records:
            return 0.0
        return statistics.mean(r["latency_ms"] for r in self._records)

    @property
    def p95_latency_ms(self) -> float:
        if not self._records:
            return 0.0
        latencies = sorted(r["latency_ms"] for r in self._records)
        idx = int(len(latencies) * 0.95)
        return latencies[idx]

    @property
    def error_rate_by_type(self) -> dict[str, int]:
        errors: dict[str, int] = defaultdict(int)
        for r in self._records:
            if not r["success"] and r["error_type"]:
                errors[r["error_type"]] += 1
        return dict(errors)


class PerformanceTracker:
    """Collects and queries tool performance metrics.

    Usage::
        tracker = PerformanceTracker()
        tracker.record_call("get_weather", latency_ms=120, success=True)
        score = tracker.composite_score("get_weather", relevance=0.85)
    """

    def __init__(self) -> None:
        self._metrics: dict[str, ToolPerformanceMetrics] = {}
        self._settings = get_settings().tools

    def record_call(
        self,
        tool_id: str,
        latency_ms: float,
        success: bool,
        error_type: str | None = None,
    ) -> None:
        """Record a single tool execution for performance tracking."""
        if tool_id not in self._metrics:
            self._metrics[tool_id] = ToolPerformanceMetrics(tool_id)
        self._metrics[tool_id].record(latency_ms, success, error_type)

    def get_metrics(self, tool_id: str) -> ToolPerformanceMetrics | None:
        return self._metrics.get(tool_id)

    def composite_score(
        self,
        tool_id: str,
        relevance: float = 0.5,
    ) -> float:
        """Compute a combined relevance + performance score.

        score = relevance * relevance_weight + performance * (1 - relevance_weight)

        Performance sub-score (0-1) combines:
        - success_rate (40%)
        - inverse normalized latency (35%)
        - normalized throughput (25%)
        """
        metrics = self._metrics.get(tool_id)
        if metrics is None or metrics.total_calls == 0:
            return relevance

        perf_weight = getattr(self._settings, "performance_weight", 0.4)

        # Performance sub-score
        success_score = metrics.success_rate
        latency_score = 1.0 - min(metrics.avg_latency_ms / 10000.0, 1.0)  # 10s = max
        throughput = metrics.total_calls / max(
            (self._settings.performance_window_minutes if hasattr(self._settings, "performance_window_minutes") else 60), 1
        )
        throughput_score = min(throughput / 10.0, 1.0)

        performance = (
            0.4 * success_score
            + 0.35 * latency_score
            + 0.25 * throughput_score
        )

        return relevance * (1 - perf_weight) + performance * perf_weight

    def is_degraded(self, tool_id: str) -> bool:
        """Check if a tool's recent performance indicates degradation.

        A tool is degraded if:
        - success_rate < error_rate_threshold (default 30%)
        - avg_latency > latency_multiplier_threshold * baseline (default 3x)
        """
        metrics = self._metrics.get(tool_id)
        if metrics is None or metrics.total_calls < getattr(self._settings, "degradation_min_samples", 5):
            return False

        settings = self._settings
        error_thresh = getattr(settings, "degradation_error_rate", 0.3)
        latency_mult = getattr(settings, "degradation_latency_multiplier", 3.0)
        cooldown_min = getattr(settings, "degradation_cooldown_minutes", 15)

        if metrics.success_rate < error_thresh:
            logger.warning("performance.degraded", tool=tool_id, reason="high_error_rate",
                           rate=metrics.success_rate, threshold=error_thresh)
            return True

        # Compare against global average latency across all tools
        all_latencies = [m.avg_latency_ms for m in self._metrics.values() if m.total_calls > 0]
        if all_latencies:
            global_avg = statistics.mean(all_latencies)
            if global_avg > 0 and metrics.avg_latency_ms > global_avg * latency_mult:
                logger.warning("performance.degraded", tool=tool_id, reason="high_latency",
                               latency=metrics.avg_latency_ms, multiplier=metrics.avg_latency_ms / global_avg)
                return True

        return False


performance_tracker = PerformanceTracker()
"""Default singleton PerformanceTracker instance."""
