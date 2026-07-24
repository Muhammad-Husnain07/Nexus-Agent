"""Clear output_schema for web_search to skip output validation."""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

DATABASE_URL = "postgresql+asyncpg://nexus:nexus@localhost:5433/nexus"

async def main():
    engine = create_async_engine(DATABASE_URL)
    async with AsyncSession(engine) as session:
        result = await session.execute(
            text("UPDATE tool SET endpoint_url = 'http://localhost:8081/search', enabled = true, output_schema = '{}'::jsonb WHERE name = 'web_search' RETURNING id, endpoint_url, enabled")
        )
        row = result.fetchone()
        if row:
            print(f"Updated! id={row[0]} endpoint={row[1]} enabled={row[2]}")
        else:
            print("web_search not found in DB")
        await session.commit()
    await engine.dispose()

asyncio.run(main())
