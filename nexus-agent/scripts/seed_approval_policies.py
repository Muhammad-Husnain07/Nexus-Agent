"""Seed ApprovalPolicy records (upsert) for HITL testing."""
import asyncio
import uuid

from sqlalchemy import delete, select

from nexus.db.base import async_session
from nexus.db.models.approval import ApprovalPolicy

POLICIES = [
    {
        "name": "high_risk_approval",
        "description": "All high-risk tools require manager approval.",
        "trigger": {"risk_level": "high", "capability": "*"},
        "steps": [
            {"step_id": "manager", "role": "manager", "ttl_seconds": 600, "escalation_role": ""},
        ],
        "priority": 100,
    },
    {
        "name": "medium_risk_approval",
        "description": "Medium-risk tools require a single reviewer approval.",
        "trigger": {"risk_level": "medium", "capability": "*"},
        "steps": [
            {"step_id": "reviewer", "role": "reviewer", "ttl_seconds": 900, "escalation_role": ""},
        ],
        "priority": 50,
    },
]


async def seed():
    async with async_session() as session:
        for pol in POLICIES:
            result = await session.execute(
                select(ApprovalPolicy).where(ApprovalPolicy.name == pol["name"])
            )
            if result.scalar_one_or_none():
                await session.execute(
                    delete(ApprovalPolicy).where(ApprovalPolicy.name == pol["name"])
                )
            session.add(ApprovalPolicy(id=uuid.uuid4(), **pol))
            print(f"Policy '{pol['name']}' seeded.")
        await session.commit()
        print("Approval policies committed!")


if __name__ == "__main__":
    asyncio.run(seed())
