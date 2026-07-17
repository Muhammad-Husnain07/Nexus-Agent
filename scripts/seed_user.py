"""Seed user and tenant."""
import asyncio, uuid
from nexus.db.base import get_session_factory
from nexus.db.models.tenant import Tenant
from nexus.db.models.user import User

async def s():
    async with get_session_factory()() as session:
        t = Tenant(id=uuid.UUID("11111111-1111-4111-8111-111111111111"), name="Demo", slug="demo")
        await session.merge(t)
        u = User(id=uuid.UUID("00000000-0000-0000-0000-000000000001"), tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"), email="dev@demo.com", role="developer")
        await session.merge(u)
        await session.commit()
        print("OK")

asyncio.run(s())
