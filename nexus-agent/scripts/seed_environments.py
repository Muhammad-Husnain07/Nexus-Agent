"""Seed deployment environments for the resolver.

Creates ``dev`` and ``prod`` environment rows with empty endpoint override
dicts (a fresh environment has no overrides — overrides are added by
operators per capability via the DB). Re-running is idempotent: existing
environments are left untouched.

Usage::

    python scripts/seed_environments.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from nexus.db.base import async_session
from nexus.db.models.environment import Environment

ENVIRONMENTS = [
    {"name": "dev", "description": "Development environment (no overrides)"},
    {"name": "prod", "description": "Production environment (no overrides)"},
]


async def main() -> None:
    async with async_session() as session:
        created = 0
        for env in ENVIRONMENTS:
            existing = await session.execute(
                select(Environment).where(Environment.name == env["name"])
            )
            if existing.scalars().first() is not None:
                continue
            session.add(Environment(**env))
            created += 1
        await session.commit()
        print(f"environments created: {created}")


if __name__ == "__main__":
    asyncio.run(main())
