"""Cost tracker — accumulates LLM costs and persists to AgentRun."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import AgentRun


class CostTracker:
    """Accumulates LLM costs for an agent run and persists to the database.

    Usage:
        tracker = CostTracker(session, agent_run_id)
        tracker.record(cost_usd=0.0032)
        await tracker.flush()
    """

    def __init__(self, session: AsyncSession, agent_run_id: uuid.UUID) -> None:
        self._session = session
        self._agent_run_id = agent_run_id
        self._accumulated_cost: float = 0.0

    def record(self, cost_usd: float) -> None:
        """Record a cost increment for the current agent run.

        Args:
            cost_usd: Cost in USD to add to the running total.
        """
        self._accumulated_cost += cost_usd

    async def flush(self) -> None:
        """Persist the accumulated cost to the AgentRun record in the database."""
        if self._accumulated_cost == 0.0:
            return

        result = await self._session.execute(
            select(AgentRun).where(AgentRun.id == self._agent_run_id)
        )
        agent_run = result.scalar_one_or_none()
        if agent_run is not None:
            agent_run.total_cost_usd += self._accumulated_cost
            await self._session.flush()
        self._accumulated_cost = 0.0

    @property
    def accumulated_cost(self) -> float:
        return self._accumulated_cost

    async def __aenter__(self) -> CostTracker:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.flush()
