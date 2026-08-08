"""Seed WorkflowTemplates for dashboard creation + market analysis (Upsert logic)."""
import asyncio
import uuid

from sqlalchemy import delete, select

from nexus.db.base import async_session
from nexus.db.models.workflow_template import WorkflowTemplate

DASHBOARD_CHAIN = [
    {
        "id": "step_1",
        "description": "List available datasources",
        "intent": "list_datasources",
        "requires_input": True,
        "question": "I can build a dashboard for you. Which datasource would you like to use?",
        "inputs": {},
    },
    {
        "id": "step_2",
        "description": "List tables in the selected datasource",
        "intent": "list_tables",
        "requires_input": True,
        "question": "Great. Which table contains the data you want to visualize?",
        "inputs": {"datasource": "${step_1}"},
    },
    {
        "id": "step_3",
        "description": "Get columns for the selected table",
        "intent": "get_table_columns",
        "requires_input": False,
        "inputs": {"table_name": "${step_2}"},
    },
    {
        "id": "step_4",
        "description": "Query the data",
        "intent": "query_table_data",
        "requires_input": False,
        "inputs": {
            "table": "${step_2}",
            "columns": "${step_3.results}",
        },
    },
    {
        "id": "step_5",
        "description": "Create the dashboard artifact",
        "intent": "create_dashboard",
        "requires_input": False,
        "inputs": {
            "title": "ATM Failures Dashboard",
            "widgets": "${step_4.results}",
        },
    },
]

# Parallel-branch workflow: step_1 and step_2 are INDEPENDENT (no cross
# references) — the DAG planner must batch them into one parallel wave.
MARKET_CHAIN = [
    {
        "id": "step_1",
        "description": "Query banking transactions",
        "intent": "query_table_data",
        "requires_input": True,
        "question": "Which banking table should we analyze?",
        "inputs": {
            "table": "transactions",
            "columns": ["amount", "status"],
        },
    },
    {
        "id": "step_2",
        "description": "Query retail orders",
        "intent": "query_table_data",
        "requires_input": True,
        "question": "Which retail table should we analyze?",
        "inputs": {
            "table": "orders",
            "columns": ["total", "status"],
        },
    },
    {
        "id": "step_3",
        "description": "Create the market analysis dashboard",
        "intent": "create_dashboard",
        "requires_input": False,
        "inputs": {
            "title": "Market Analysis Dashboard",
            "widgets": "${step_1.results}",
        },
    },
]


# Hybrid workflow: the final step is ``dynamic`` — its capability is NOT
# fixed; the SemanticPlanner plans it at runtime from the step description.
# Exercises workflow → dynamic-planning composition (hybrid execution).
HYBRID_CHAIN = [
    {
        "id": "step_1",
        "description": "List available datasources",
        "intent": "list_datasources",
        "requires_input": True,
        "question": "Which datasource would you like to use?",
        "inputs": {},
    },
    {
        "id": "step_2",
        "description": "Inspect the selected datasource and summarize its tables",
        "intent": "list_tables",
        "requires_input": True,
        "question": "Which table should we summarize?",
        "inputs": {"datasource": "${step_1}"},
    },
    {
        "id": "step_3",
        "description": "Produce a useful analysis artifact for the chosen table",
        "intent": "",
        "dynamic": True,
        "requires_input": False,
        "question": "",
        "inputs": {"table": "${step_2}"},
    },
]


async def _upsert(session, name: str, pattern: str, description: str, chain: list[dict], priority: int = 10) -> None:
    result = await session.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.name == name)
    )
    existing = result.scalar_one_or_none()
    if existing:
        await session.execute(delete(WorkflowTemplate).where(WorkflowTemplate.name == name))
        print(f"Existing template '{name}' deleted.")

    template = WorkflowTemplate(
        id=uuid.uuid4(),
        name=name,
        trigger_intent_pattern=pattern,
        description=description,
        priority=priority,
        enabled=True,
        capability_chain=chain,
    )
    session.add(template)
    print(f"Template '{name}' seeded (priority={priority}).")


async def seed():
    async with async_session() as session:
        await _upsert(
            session,
            "dashboard_creation",
            "dashboard",
            "Creates a data dashboard by iterating through datasources, tables, and columns.",
            DASHBOARD_CHAIN,
        )
        await _upsert(
            session,
            "market_analysis",
            "market",
            "Analyzes banking and retail data in parallel and builds a market dashboard.",
            MARKET_CHAIN,
            priority=100,
        )
        await _upsert(
            session,
            "hybrid_analysis",
            "hybrid",
            "Collects a datasource and table, then DYNAMICALLY plans the final analysis step.",
            HYBRID_CHAIN,
            priority=90,
        )
        await session.commit()
        print("All templates committed successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
