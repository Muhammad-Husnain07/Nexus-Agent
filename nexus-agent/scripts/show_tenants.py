"""Show tenants and user-tenant relationships."""
import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sqlalchemy import text
from nexus.db.base import get_engine

async def main():
    engine = get_engine()
    async with engine.begin() as conn:
        rows = await conn.execute(text("SELECT id, name, slug FROM tenant"))
        print("Tenants:")
        for r in rows:
            print(f"  {r.name} (id: {r.id}, slug: {r.slug})")
        rows2 = await conn.execute(text("SELECT id, email, tenant_id FROM public.user"))
        print("\nUsers with their tenants:")
        for r in rows2:
            print(f"  {r.email} (user_id: {r.id}, tenant_id: {r.tenant_id})")
    await engine.dispose()

asyncio.run(main())
