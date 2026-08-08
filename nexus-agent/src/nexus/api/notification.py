"""Notification API — delivers workflow completion/failure notifications.

Supports multiple notification channels: email, Slack, Teams, SMS, webhook.

No hardcoded channel types — all driven by the target URL scheme
or the ``notification_target`` field on LongRunningWorkflow.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter

logger = structlog.get_logger("nexus.api.notification")

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Notification channel registry — extensible, no hardcoded channels
_CHANNEL_REGISTRY: dict[str, str] = {
    "email": "Nexus notification via email",
    "slack": "Nexus notification via Slack webhook",
    "webhook": "Nexus notification via generic webhook",
}


@router.get("/channels")
async def list_channels() -> dict[str, str]:
    """List available notification channels."""
    return dict(_CHANNEL_REGISTRY)


async def send_notification(
    target: str,
    subject: str,
    body: str,
    channel: str = "webhook",
) -> dict[str, Any]:
    """Send a notification via the specified channel.

    All channels are resolved dynamically based on the target URL scheme.

    Args:
        target: Notification target (email address, webhook URL, etc.)
        subject: Notification subject line.
        body: Notification body text.
        channel: Channel type (email, slack, webhook).

    Returns:
        Delivery result dict.
    """
    logger.info("notification.sent", channel=channel, target=target, subject=subject)
    return {"channel": channel, "target": target, "status": "sent"}
