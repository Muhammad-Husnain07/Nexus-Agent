"""Seed the registry (capability, provider, endpoint, goal_template) from existing Tool records.

Usage::

    uv run python scripts/seed_registry.py
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import insert as sa_insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from nexus.config.settings import get_settings
from nexus.db.models.registry import (
    CapabilityModel, EndpointModel, GoalTemplateModel, ProviderModel,
    goal_template_capability,
)
from nexus.db.models.tool import Tool


def _derive_capability_name(tool: Tool) -> str:
    category_map = {
        "entertainment": "entertainment", "reference": "reference", "search": "search",
        "bookmarks": "bookmark", "utilities": "utility", "finance": "finance",
        "data": "data", "fun": "fun",
    }
    base = category_map.get(tool.category, tool.category)
    return f"{base}_{tool.name}"


def _derive_ontology_parent(tool: Tool) -> str | None:
    if tool.category in ("entertainment", "fun"):
        return "media"
    if tool.category == "data":
        return "data_services"
    if tool.category == "bookmarks":
        return "storage"
    if tool.category == "search":
        return "search"
    if tool.category in ("reference",):
        return "reference"
    if tool.category == "finance":
        return "finance"
    if tool.category == "utilities":
        return "utility"
    return None


def _build_consumes_produces(tool: Tool) -> tuple[list[str], list[str]]:
    inputs = tool.input_schema or {}
    outputs = tool.output_schema or {}
    consumes = list(inputs.get("properties", {}).keys()) if isinstance(inputs, dict) else []
    produces = list(outputs.get("properties", {}).keys()) if isinstance(outputs, dict) else []
    return consumes, produces


async def seed_registry(dry_run: bool = False) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database.url.replace("+asyncpg", "+psycopg"))

    async with AsyncSession(engine) as session:
        result = await session.execute(select(Tool).where(Tool.enabled == True))
        tools = result.scalars().all()
        if not tools:
            print("No enabled tools found.")
            return

        print(f"Found {len(tools)} enabled tools. Generating registry entries...")
        cap_count = prov_count = endp_count = tmpl_count = 0

        for tool in tools:
            cap_name = _derive_capability_name(tool)
            consumes, produces = _build_consumes_produces(tool)
            ontology_parent = _derive_ontology_parent(tool)

            if not dry_run:
                capability = CapabilityModel(
                    id=tool.id, name=cap_name, description=tool.description or tool.purpose or "",
                    ontology_parent=ontology_parent, consumes=consumes, produces=produces,
                    tags=tool.tags or [],
                    contract={"idempotent": tool.http_method in ("GET", "PUT", "DELETE"),
                              "risk_level": tool.risk_level or "low",
                              "requires_approval": tool.requires_approval or False},
                    version=tool.version or 1,
                )
                session.add(capability)

                provider = ProviderModel(
                    id=uuid.uuid4(), capability_id=tool.id, name=f"{tool.name}_provider",
                    description=f"Default provider for {tool.name}",
                    sla_p99_ms=5000, cost_per_call=0.0, privacy_level="low", retry_policy="default",
                )
                session.add(provider)
                endpoint = EndpointModel(
                    id=uuid.uuid4(), provider_id=provider.id, url=tool.endpoint_url,
                    http_method=tool.http_method or "GET", auth_type=tool.auth_type or "none", weight=1,
                )
                session.add(endpoint)
                cap_count += 1; prov_count += 1; endp_count += 1
            else:
                cap_count += 1; prov_count += 1; endp_count += 1

            print(f"  {tool.name:30s} -> capability={cap_name:30s} consumes={consumes}")

            # Goal template — one per tool
            parts = tool.name.split("_")
            prefix = parts[0] if len(parts) > 0 else "retrieve"
            if prefix == "get":
                prefix = "retrieve"
            tmpl_name = f"{prefix}_{tool.name}"

            if not dry_run:
                goal_template = GoalTemplateModel(
                    id=uuid.uuid4(), name=tmpl_name, trigger_action=tool.name,
                    expansion_logic={"steps": [{"capability": cap_name, "inputs": tool.input_schema or {}}]},
                    version=1,
                )
                session.add(goal_template)
                await session.flush()
                await session.execute(
                    sa_insert(goal_template_capability).values(
                        goal_template_id=goal_template.id, capability_id=tool.id,
                    )
                )

            tmpl_count += 1
            print(f"  template: {tmpl_name:30s}")

        if not dry_run:
            await session.commit()
            print(f"\nCommitted: {cap_count} capabilities, {prov_count} providers, "
                  f"{endp_count} endpoints, {tmpl_count} templates")
        else:
            print(f"\nDry-run: would create {cap_count} capabilities, {prov_count} providers, "
                  f"{endp_count} endpoints, {tmpl_count} templates")

    await engine.dispose()


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    asyncio.run(seed_registry(dry_run=dry))
