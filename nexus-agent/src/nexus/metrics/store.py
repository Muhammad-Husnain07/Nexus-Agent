"""Metrics Store — EWMA-based reliability tracking for providers and capabilities.

Uses Exponentially Weighted Moving Average (EWMA) to update provider reliability
scores after each execution. The formula prevents a single failure from
blacklisting a provider while still adapting to persistent degradation.

``alpha`` controls the smoothing factor (default 0.3).
Higher alpha = more weight on recent observations (faster adaptation).
Lower alpha = smoother (less oscillation).
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from sqlalchemy import select, update

from nexus.db.base import async_session as _async_session
from nexus.db.models.registry import ProviderModel

logger = structlog.get_logger("nexus.metrics.store")

_DEFAULT_ALPHA: float = 0.3


def ewma_update(
    current_reliability: float,
    success: bool,
    alpha: float = _DEFAULT_ALPHA,
) -> float:
    """Compute the new EWMA reliability score.

    Formula::

        new = alpha * observation + (1 - alpha) * current

    Where ``observation`` is 1.0 for success, 0.0 for failure.

    Args:
        current_reliability: The current EWMA score (0.0–1.0).
        success: Whether the execution succeeded.
        alpha: Smoothing factor (default 0.3).

    Returns:
        Updated reliability score.
    """
    observation = 1.0 if success else 0.0
    return alpha * observation + (1.0 - alpha) * current_reliability


async def update_provider_reliability(
    provider_name: str,
    success: bool,
    alpha: float = _DEFAULT_ALPHA,
) -> float | None:
    """Update a provider's EWMA reliability score in the database.

    Looks up the provider by name, computes the new score, and persists it.

    Args:
        provider_name: The provider name (e.g. ``get_pokemon_provider``).
        success: Whether the execution succeeded.
        alpha: EWMA smoothing factor.

    Returns:
        The new reliability score, or None if provider not found.
    """
    async with _async_session() as sess:
        result = await sess.execute(
            select(ProviderModel).where(ProviderModel.name == provider_name)
        )
        provider = result.scalar_one_or_none()
        if provider is None:
            logger.warning("metrics.provider_not_found", provider=provider_name)
            return None

        new_score = ewma_update(provider.reliability_score, success, alpha)
        await sess.execute(
            update(ProviderModel)
            .where(ProviderModel.name == provider_name)
            .values(reliability_score=new_score)
        )
        await sess.commit()
        logger.info(
            "metrics.provider_reliability_updated",
            provider=provider_name,
            old=round(provider.reliability_score, 4),
            new=round(new_score, 4),
            alpha=alpha,
        )
        return new_score


async def get_provider_reliability(provider_name: str) -> float | None:
    """Get the current EWMA reliability score for a provider.

    Args:
        provider_name: The provider name.

    Returns:
        Reliability score (0.0–1.0) or None if not found.
    """
    async with _async_session() as sess:
        result = await sess.execute(
            select(ProviderModel.reliability_score).where(ProviderModel.name == provider_name)
        )
        score = result.scalar_one_or_none()
        return score
