"""Backfill keywords for all existing tools that lack precomputed keywords.

Usage:
    uv run python scripts/backfill_keywords.py
"""

import asyncio
import sys

from sqlalchemy import select

from nexus.db.base import async_session
from nexus.db.models.tool import Tool
from nexus.tools.keywords import extract_keywords


async def main():
    print("Backfilling tool keywords...")
    count = 0
    async with async_session() as session:
        result = await session.execute(select(Tool))
        tools = result.scalars().all()
        for tool in tools:
            keywords = extract_keywords(
                name=tool.name,
                purpose=tool.purpose or "",
                tags=tool.tags,
                aliases=tool.aliases,
            )
            if keywords != (tool.keywords or []):
                tool.keywords = keywords
                count += 1
        await session.flush()
        await session.commit()
    print(f"Updated {count} tools with keywords.")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
