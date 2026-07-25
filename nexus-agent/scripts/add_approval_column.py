"""Add requires_approval column to tool table."""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

DATABASE_URL = "postgresql+asyncpg://nexus:nexus@localhost:5433/nexus"

async def main():
    engine = create_async_engine(DATABASE_URL)
    async with AsyncSession(engine) as session:
        try:
            await session.execute(
                text("ALTER TABLE tool ADD COLUMN requires_approval BOOLEAN DEFAULT FALSE NOT NULL")
            )
            await session.commit()
            print("Column 'requires_approval' added successfully")
        except Exception as e:
            await session.rollback()
            if "already exists" in str(e):
                print("Column already exists")
            else:
                print(f"Error: {e}")
    await engine.dispose()

asyncio.run(main())
