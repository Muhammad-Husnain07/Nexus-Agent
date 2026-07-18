"""Seed database with a development tenant and admin user."""
import asyncio

from nexus.db.base import async_session
from nexus.db.models.tenant import Tenant
from nexus.db.models.user import User
from nexus.db.repositories.base import GenericRepository


async def seed() -> None:
    async with async_session() as session:
        repo = GenericRepository(session, Tenant)
        tenant = await repo.create(name="Demo Org", slug="demo", status="active", settings={})
        await session.flush()
        user_repo = GenericRepository(session, User)
        user = await user_repo.create(
            tenant_id=tenant.id,
            email="admin@demo.com",
            role="tenant_admin",
            external_id="demo-admin",
        )
        await session.commit()
        print(f"Tenant: {tenant.id} / {tenant.slug}")
        print(f"User: {user.id} / {user.email} / {user.role}")


if __name__ == "__main__":
    asyncio.run(seed())
