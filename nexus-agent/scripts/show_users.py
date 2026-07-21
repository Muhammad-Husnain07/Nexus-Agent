"""Show users in the database."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sqlalchemy import text
from nexus.db.base import get_engine

async def main():
    engine = get_engine()
    async with engine.begin() as conn:
        rows = await conn.execute(text("SELECT id, email, role FROM public.user"))
        print("Users in database:")
        for r in rows:
            print(f"  {r.email} (role: {r.role}, id: {r.id})")
    await engine.dispose()

asyncio.run(main())
