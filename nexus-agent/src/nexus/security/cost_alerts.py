"""Cost alert webhooks — Slack notifications at configurable thresholds."""

from __future__ import annotations

import uuid

import httpx
import structlog

logger = structlog.get_logger("nexus.security.cost_alerts")

ALERT_THRESHOLDS = [0.50, 0.80, 1.00]  # 50%, 80%, 100% of daily cap


class CostAlertService:
    """Fires Slack webhook notifications when cost thresholds are breached."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http = http_client or httpx.AsyncClient()

    async def check_and_alert(
        self,
        tenant_id: uuid.UUID,
        cost_usd: float,
        max_cost_per_day: float,
        slack_webhook_url: str | None = None,
        alerted_thresholds: set[float] | None = None,
    ) -> set[float]:
        """Check cost ratio and fire alerts for newly-breached thresholds.

        Args:
            tenant_id: The tenant to evaluate.
            cost_usd: Current day's accumulated cost.
            max_cost_per_day: Daily cost cap.
            slack_webhook_url: Slack incoming webhook URL (from tenant settings).
            alerted_thresholds: Set of thresholds already alerted today.

        Returns:
            Updated set of alerted thresholds.
        """
        if max_cost_per_day <= 0 or not slack_webhook_url:
            return alerted_thresholds or set()

        alerted = set(alerted_thresholds or set())
        ratio = cost_usd / max_cost_per_day

        for threshold in ALERT_THRESHOLDS:
            if ratio >= threshold and threshold not in alerted:
                await self._send_alert(
                    webhook_url=slack_webhook_url,
                    tenant_id=tenant_id,
                    ratio=ratio,
                    threshold=threshold,
                    cost_usd=cost_usd,
                    max_cost=max_cost_per_day,
                )
                alerted.add(threshold)

        return alerted

    async def _send_alert(
        self,
        webhook_url: str,
        tenant_id: uuid.UUID,
        ratio: float,
        threshold: float,
        cost_usd: float,
        max_cost: float,
    ) -> None:
        payload = {
            "text": (
                f":warning: *Nexus Agent — Cost Alert*\n"
                f"*Tenant:* `{tenant_id}`\n"
                f"*Usage:* ${cost_usd:.2f} / ${max_cost:.2f} "
                f"({ratio:.1%})\n"
                f"*Threshold:* {threshold:.0%}\n"
                f"*Action:* {'Degrade to cheap model' if threshold >= 1.0 else 'Monitor'}"
            ),
        }

        try:
            resp = await self._http.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info("cost.alert_sent", tenant_id=str(tenant_id), threshold=threshold)
        except Exception as exc:
            logger.warning("cost.alert_failed", tenant_id=str(tenant_id), error=str(exc))

    async def close(self) -> None:
        await self._http.aclose()
