"""Standalone seed script — registers all free API tools and demo data.

Usage:
    uv run python scripts/seed.py                # full seed (embeddings via Ollama)
    uv run python scripts/seed.py --no-embed     # skip embeddings
    uv run python scripts/seed.py --reset        # drop and re-register
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import text

from nexus.config.settings import get_settings
from nexus.db.base import get_engine
from nexus.db.models.tenant import Tenant
from nexus.db.models.user import User
from nexus.tools.registry import ToolRegistry
from nexus.tools.schemas import ToolCreate

DEMO_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


# ── Tool definitions ─────────────────────────────────────────────────────────

TOOLS: list[ToolCreate] = [
    ToolCreate(
        name="geocode_city",
        description="Convert a city name (e.g. 'London', 'Tokyo') to geographic latitude/longitude coordinates. Takes a 'city' parameter. Use this BEFORE open_meteo_forecast.",
        endpoint_url="https://geocoding-api.open-meteo.com/v1/search",
        http_method="GET",
        input_schema={
            "type": "object",
            "required": ["city"],
            "properties": {
                "city": {"type": "string", "description": "City name (e.g. London, Tokyo, New York)"},
                "count": {"type": "integer", "default": 1, "description": "Number of results"},
            },
        },
        output_schema={"type": "object"},
        tags=["weather", "geocoding"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="open_meteo_forecast",
        description="Get a weather forecast for a location using its latitude and longitude coordinates. Returns temperature, conditions, humidity, wind speed.",
        endpoint_url="https://api.open-meteo.com/v1/forecast",
        http_method="GET",
        input_schema={
            "type": "object",
            "required": ["latitude", "longitude"],
            "properties": {
                "latitude": {"type": "number", "description": "Latitude"},
                "longitude": {"type": "number", "description": "Longitude"},
            },
        },
        output_schema={"type": "object"},
        tags=["weather", "forecast"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="get_joke",
        description="Fetch a random programming or general joke. Pure entertainment.",
        endpoint_url="https://v2.jokeapi.dev/joke/Programming?type=single",
        http_method="GET",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        tags=["fun", "entertainment"],
        category="entertainment",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="cat_fact",
        description="Return a random fun fact about cats.",
        endpoint_url="https://catfact.ninja/fact",
        http_method="GET",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        tags=["fun", "animals"],
        category="entertainment",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="random_user",
        description="Generate a random user profile (name, email, address, phone, picture).",
        endpoint_url="https://randomuser.me/api/",
        http_method="GET",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        tags=["demo", "data"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="brewery_list",
        description="Search for breweries by city or name.",
        endpoint_url="https://api.openbrewerydb.org/v1/breweries",
        http_method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "by_city": {"type": "string", "description": "City name"},
                "by_name": {"type": "string", "description": "Brewery name"},
            },
        },
        output_schema={"type": "object"},
        tags=["food", "drink"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="agify_predict_age",
        description="Predict age from a given name.",
        endpoint_url="https://api.agify.io/",
        http_method="GET",
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "First name"}},
        },
        output_schema={"type": "object"},
        tags=["fun", "data"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="genderize_predict",
        description="Predict gender from a given name.",
        endpoint_url="https://api.genderize.io/",
        http_method="GET",
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "First name"}},
        },
        output_schema={"type": "object"},
        tags=["fun", "data"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="nationalize_predict",
        description="Predict nationality from a given name.",
        endpoint_url="https://api.nationalize.io/",
        http_method="GET",
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "First name"}},
        },
        output_schema={"type": "object"},
        tags=["fun", "data"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="coindesk_bitcoin_price",
        description="Get current Bitcoin price in USD, GBP, EUR.",
        endpoint_url="https://api.coindesk.com/v1/bpi/currentprice.json",
        http_method="GET",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        tags=["finance", "crypto"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="bored_activity",
        description="Suggest a random activity to do when bored.",
        endpoint_url="https://bored-api.appbrewery.com/random",
        http_method="GET",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        tags=["fun", "lifestyle"],
        category="entertainment",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="dog_random_image",
        description="Return a URL to a random dog image.",
        endpoint_url="https://dog.ceo/api/breeds/image/random",
        http_method="GET",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        tags=["fun", "animals"],
        category="entertainment",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="jsonplaceholder_posts",
        description="Fetch sample blog posts from JSONPlaceholder.",
        endpoint_url="https://jsonplaceholder.typicode.com/posts",
        http_method="GET",
        input_schema={
            "type": "object",
            "properties": {
                "userId": {"type": "integer", "description": "Filter by user ID (1-10)"}
            },
        },
        output_schema={"type": "object"},
        tags=["demo", "data"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="dummyjson_search",
        description="Search products on DummyJSON by keyword.",
        endpoint_url="https://dummyjson.com/products/search",
        http_method="GET",
        input_schema={
            "type": "object",
            "required": ["q"],
            "properties": {"q": {"type": "string", "description": "Search keyword"}},
        },
        output_schema={"type": "object"},
        tags=["demo", "ecommerce"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="fakestore_products",
        description="List all products from Fake Store API.",
        endpoint_url="https://fakestoreapi.com/products",
        http_method="GET",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        tags=["demo", "ecommerce"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="university_search",
        description="Search universities worldwide by name.",
        endpoint_url="http://universities.hipolabs.com/search",
        http_method="GET",
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "University name"}},
        },
        output_schema={"type": "object"},
        tags=["education", "data"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="rest_countries_search",
        description="Search for country information by name.",
        endpoint_url="https://restcountries.com/v3.1/name",
        http_method="GET",
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string", "description": "Country name"}},
        },
        output_schema={"type": "object"},
        tags=["education", "geography"],
        category="data",
        risk_level="low",
        enabled=True,
    ),
    ToolCreate(
        name="httpbin_echo",
        description="Echo back input data for testing. Returns whatever payload you send.",
        endpoint_url="https://httpbin.org/anything",
        http_method="POST",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        tags=["dev", "testing"],
        category="dev",
        risk_level="low",
        enabled=True,
    ),
]


async def seed(no_embed: bool = False, reset: bool = False) -> None:
    settings = get_settings()
    engine = get_engine()

    async with engine.begin() as conn:
        if reset:
            await conn.execute(text("DELETE FROM tool"))
            await conn.execute(text("DELETE FROM tool_execution"))
            print("Cleared existing tools.")

        # Ensure tenant exists
        result = await conn.execute(
            text("SELECT id FROM tenant WHERE id = :id"),
            {"id": DEMO_TENANT_ID},
        )
        if not result.scalar():
            await conn.execute(
                text("INSERT INTO tenant (id, name, slug) VALUES (:id, :name, :slug)"),
                {"id": DEMO_TENANT_ID, "name": "Demo", "slug": "demo"},
            )
            print(f"Created tenant {DEMO_TENANT_ID}.")

        # Ensure user exists
        result = await conn.execute(
            text("SELECT id FROM public.user WHERE id = :id"),
            {"id": DEMO_USER_ID},
        )
        if not result.scalar():
            await conn.execute(
                text(
                    "INSERT INTO public.user (id, tenant_id, email, role) "
                    "VALUES (:id, :tenant_id, :email, :role)"
                ),
                {
                    "id": DEMO_USER_ID,
                    "tenant_id": DEMO_TENANT_ID,
                    "email": "demo@nexus.local",
                    "role": "tenant_admin",
                },
            )
            print(f"Created user {DEMO_USER_ID}.")

    # Register tools
    from nexus.db.base import async_session

    registered = 0
    async with async_session() as session:
        registry = ToolRegistry()
        for tool in TOOLS:
            existing = await registry.list(session=session, tenant_id=DEMO_TENANT_ID)
            if any(t.name == tool.name for t in existing.items):
                print(f"  Tool '{tool.name}' already exists — skipping.")
                continue
            await registry.register(
                session=session,
                tenant_id=DEMO_TENANT_ID,
                data=tool,
                skip_embedding=no_embed,
            )
            registered += 1
            print(f"  Registered '{tool.name}'.")

        await session.commit()

    print(f"\nDone! {registered} tools registered.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo tools and data")
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding generation")
    parser.add_argument("--reset", action="store_true", help="Drop existing tools first")
    args = parser.parse_args()
    asyncio.run(seed(no_embed=args.no_embed, reset=args.reset))


if __name__ == "__main__":
    main()
