"""Seed demo tools and test user for the working demo.
Runs as a standalone script. Must be run from the nexus-agent directory
with the virtual environment activated.
"""
import asyncio
import os
import sys
import uuid

# Ensure src/ is on the path so we can import nexus modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from nexus.config.settings import get_settings

BASE = "http://localhost:8000"
TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

DEMO_TOOLS = [
    {
        "name": "search_products",
        "description": "Searches for products by keyword using MercadoLibre. Returns titles, prices, and URLs.",
        "purpose": "Use this when the user wants to search for products, shop, compare prices, or find items for sale.",
        "tool_type": "http_api",
        "endpoint_url": "https://api.mercadolibre.com/sites/MLA/search",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search keyword or product name"},
                "limit": {"type": "integer", "default": 5, "description": "Max results"},
            },
            "required": ["q"],
        },
        "output_schema": {"type": "object"},
        "risk_level": "low",
        "requires_approval": False,
        "tags": ["search", "products", "shopping"],
        "category": "ecommerce",
    },
    {
        "name": "get_weather",
        "description": "Gets current weather for a city using wttr.in. Returns temperature, conditions, and humidity.",
        "purpose": "Use this when the user asks about weather in a specific city.",
        "tool_type": "http_api",
        "endpoint_url": "https://wttr.in",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name (e.g. London, Tokyo)"},
            },
            "required": ["city"],
        },
        "output_schema": {"type": "object"},
        "risk_level": "low",
        "requires_approval": False,
        "tags": ["weather", "info"],
        "category": "utilities",
    },
    {
        "name": "get_joke",
        "description": "Fetches a random programming joke from JokeAPI.",
        "purpose": "Use this when the user asks for a joke or wants something funny.",
        "tool_type": "http_api",
        "endpoint_url": "https://v2.jokeapi.dev/joke/Programming",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object"},
        "risk_level": "low",
        "requires_approval": False,
        "tags": ["fun", "joke"],
        "category": "entertainment",
    },
]


async def ensure_test_user():
    """Insert a test tenant + user into the DB so auth works."""
    settings = get_settings()
    engine = create_async_engine(settings.database.url)
    async with AsyncSession(engine) as session:
        # Create tenant if not exists
        from nexus.db.models.tenant import Tenant
        existing = await session.get(Tenant, TENANT_ID)
        if existing is None:
            session.add(Tenant(id=TENANT_ID, name="Demo Tenant", slug="demo-tenant"))
            await session.flush()
            print("  [OK] Created demo tenant")

        # Create user if not exists
        from nexus.db.models.user import User
        existing_user = await session.get(User, USER_ID)
        if existing_user is None:
            session.add(User(id=USER_ID, tenant_id=TENANT_ID, email="demo@nexus.local", role="tenant_admin"))
            await session.flush()
            print("  [OK] Created demo admin user")

        await session.commit()
    await engine.dispose()


def register_tools():
    """Register demo tools via the API with a valid JWT."""
    from nexus.security.auth import create_access_token
    from nexus.config.settings import get_settings as _gs
    _s = _gs()
    print(f"  [DBG] JWT secret: {_s.auth.jwt_secret.get_secret_value()[:20]}...")
    token = create_access_token(USER_ID, "tenant_admin", tenant_id=TENANT_ID)
    print(f"  [DBG] Token: {token[:60]}...")
    headers = {"Authorization": f"Bearer {token}"}

    r = httpx.get(f"{BASE}/api/v1/tools", headers=headers, params={"enabled": True})
    existing = {t["name"] for t in r.json().get("items", [])}

    for td in DEMO_TOOLS:
        if td["name"] in existing:
            print(f"  [OK] Already exists: {td['name']}")
            continue
        r2 = httpx.post(f"{BASE}/api/v1/tools", json=td, headers=headers)
        if r2.status_code in (200, 201):
            print(f"  [OK] Registered: {td['name']}")
        elif r2.status_code == 422:
            print(f"  [-] Validation error for {td['name']}: {r2.text[:150]}")
        else:
            print(f"  [ERR] {td['name']}: {r2.status_code} {r2.text[:100]}")

    # Confirm
    r = httpx.get(f"{BASE}/api/v1/tools", headers=headers, params={"enabled": True})
    data = r.json()
    print(f"\n  Tools registered: {len(data.get('items', []))}")
    for t in data.get("items", []):
        print(f"    - {t['name']} ({t['tool_type']})")


if __name__ == "__main__":
    print("Seeding demo data...")
    asyncio.run(ensure_test_user())
    print()
    register_tools()
    print("\nDone! Demo is ready.")
