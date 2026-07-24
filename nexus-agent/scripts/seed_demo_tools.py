"""Seed demo tools — registers the standard demo set with real public APIs."""

import asyncio
import httpx

BASE_URL = "http://localhost:8000/api/v1"

TOOLS = [
    {
        "name": "get_joke",
        "description": "Get a random joke with setup and punchline.",
        "purpose": "Use when the user asks for a joke, comedy, or something funny.",
        "endpoint_url": "https://official-joke-api.appspot.com/random_joke",
        "http_method": "GET",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string"}, "setup": {"type": "string"},
                "punchline": {"type": "string"}, "id": {"type": "integer"},
            },
        },
        "tags": ["fun", "joke", "entertainment"],
        "category": "entertainment",
        "risk_level": "low",
    },
    {
        "name": "get_geocoding",
        "description": "Convert a city name to latitude/longitude coordinates.",
        "purpose": "Use to convert a city name to lat/lon coordinates for weather or other location services.",
        "endpoint_url": "https://geocoding-api.open-meteo.com/v1/search",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "City name to search"},
                "count": {"type": "integer", "description": "Max results"},
            },
            "required": ["name"],
        },
        "tags": ["geo", "data", "location"],
        "category": "data",
        "risk_level": "low",
    },
    {
        "name": "get_weather",
        "description": "Get current weather for coordinates (latitude/longitude).",
        "purpose": "Use when the user asks about weather, temperature, or conditions.",
        "endpoint_url": "https://api.open-meteo.com/v1/forecast",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Latitude"},
                "longitude": {"type": "number", "description": "Longitude"},
                "current_weather": {"type": "boolean", "description": "Include current weather"},
            },
            "required": ["latitude", "longitude"],
        },
        "tags": ["weather", "data", "forecast"],
        "category": "data",
        "risk_level": "low",
    },
    {
        "name": "get_cat_fact",
        "description": "Get a random cat fact.",
        "purpose": "Use when the user asks about cats or cat facts.",
        "endpoint_url": "https://catfact.ninja/fact",
        "http_method": "GET",
        "input_schema": {"type": "object", "properties": {}},
        "tags": ["fun", "facts", "animals"],
        "category": "fun",
        "risk_level": "low",
    },
    {
        "name": "get_dog_image",
        "description": "Get a random dog image URL.",
        "purpose": "Use when the user asks for a dog picture or dog image.",
        "endpoint_url": "https://dog.ceo/api/breeds/image/random",
        "http_method": "GET",
        "input_schema": {"type": "object", "properties": {}},
        "tags": ["fun", "animals", "dogs"],
        "category": "fun",
        "risk_level": "low",
    },
    {
        "name": "predict_age",
        "description": "Predict age from a first name.",
        "purpose": "Use when the user asks to predict age from a name.",
        "endpoint_url": "https://api.agify.io",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "First name"}},
            "required": ["name"],
        },
        "tags": ["demographics", "fun"],
        "category": "data",
        "risk_level": "low",
    },
    {
        "name": "predict_nationality",
        "description": "Predict nationality from a first name.",
        "purpose": "Use when user asks to predict nationality or country from a name.",
        "endpoint_url": "https://api.nationalize.io",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "First name"}},
            "required": ["name"],
        },
        "tags": ["demographics", "fun"],
        "category": "data",
        "risk_level": "low",
    },
    {
        "name": "get_trivia",
        "description": "Get random trivia questions.",
        "purpose": "Use when user asks for trivia, quiz, or fun facts.",
        "endpoint_url": "https://opentdb.com/api.php",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "integer", "description": "Number of questions (1-10)"},
                "difficulty": {"type": "string", "description": "easy, medium, or hard"},
            },
            "required": ["amount"],
        },
        "tags": ["trivia", "quiz", "entertainment"],
        "category": "entertainment",
        "risk_level": "low",
    },
    {
        "name": "get_crypto_price",
        "description": "Get current cryptocurrency prices in any currency.",
        "purpose": "Use when user asks about cryptocurrency prices, Bitcoin, Ethereum, etc.",
        "endpoint_url": "https://api.coingecko.com/api/v3/simple/price",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "ids": {"type": "string", "description": "Coin IDs (e.g. bitcoin,ethereum)"},
                "vs_currencies": {"type": "string", "description": "Currency (e.g. usd,eur)"},
            },
            "required": ["ids", "vs_currencies"],
        },
        "tags": ["finance", "crypto"],
        "category": "finance",
        "risk_level": "low",
    },
    {
        "name": "get_pokemon",
        "description": "Get information about a Pokemon by name.",
        "purpose": "Use when user asks about Pokemon characters or creatures.",
        "endpoint_url": "https://pokeapi.co/api/v2/pokemon/{name}",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Pokemon name"}},
            "required": ["name"],
        },
        "tags": ["gaming", "pokemon", "entertainment"],
        "category": "entertainment",
        "risk_level": "low",
    },
    {
        "name": "get_starwars_character",
        "description": "Get information about a Star Wars character by ID.",
        "purpose": "Use when user asks about Star Wars characters.",
        "endpoint_url": "https://swapi.dev/api/people/{id}/",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "Character ID"}},
            "required": ["id"],
        },
        "tags": ["film", "starwars", "entertainment"],
        "category": "entertainment",
        "risk_level": "low",
    },
    {
        "name": "search_art",
        "description": "Search for artworks from the Art Institute of Chicago.",
        "purpose": "Use when user asks about art, paintings, or artists.",
        "endpoint_url": "https://api.artic.edu/api/v1/artworks/search",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results"},
            },
            "required": ["q"],
        },
        "tags": ["art", "culture", "search"],
        "category": "reference",
        "risk_level": "low",
    },
    {
        "name": "search_books",
        "description": "Search for books by title, author, or keyword.",
        "purpose": "Use when user asks about books, authors, or literature.",
        "endpoint_url": "https://openlibrary.org/search.json",
        "http_method": "GET",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results"},
            },
            "required": ["q"],
        },
        "tags": ["books", "literature", "search"],
        "category": "reference",
        "risk_level": "low",
    },
    {
        "name": "echo_post",
        "description": "Send a POST request with arbitrary data and get it echoed back.",
        "purpose": "Use for testing POST requests or submitting data.",
        "endpoint_url": "https://httpbin.org/post",
        "http_method": "POST",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Any data to send"},
                "key": {"type": "string"}, "value": {"type": "string"},
            },
        },
        "tags": ["utility", "test", "http"],
        "category": "utilities",
        "risk_level": "low",
    },
    {
        "name": "echo_put",
        "description": "Send a PUT request with arbitrary data and get it echoed back.",
        "purpose": "Use for testing PUT requests or updating resources.",
        "endpoint_url": "https://httpbin.org/put",
        "http_method": "PUT",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Updated data"},
                "id": {"type": "string", "description": "Resource ID"},
            },
        },
        "tags": ["utility", "test", "update"],
        "category": "utilities",
        "risk_level": "low",
    },
    {
        "name": "echo_patch",
        "description": "Send a PATCH request with partial data and get it echoed back.",
        "purpose": "Use for testing PATCH requests or partially updating resources.",
        "endpoint_url": "https://httpbin.org/patch",
        "http_method": "PATCH",
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {"type": "string", "description": "Field name to update"},
                "id": {"type": "string", "description": "Resource ID"},
                "value": {"type": "string", "description": "New value"},
            },
        },
        "tags": ["utility", "test", "partial"],
        "category": "utilities",
        "risk_level": "low",
    },
    {
        "name": "echo_delete",
        "description": "Send a DELETE request with optional ID and get confirmation.",
        "purpose": "Use for testing DELETE requests.",
        "endpoint_url": "https://httpbin.org/delete",
        "http_method": "DELETE",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Resource ID to delete"},
                "confirm": {"type": "boolean", "description": "Confirmation flag"},
            },
        },
        "tags": ["utility", "test", "delete"],
        "category": "utilities",
        "risk_level": "low",
    },
]


async def register_all():
    async with httpx.AsyncClient(timeout=30) as client:
        for tool in TOOLS:
            try:
                resp = await client.post(f"{BASE_URL}/tools", json=tool)
                if resp.status_code == 201:
                    data = resp.json()
                    print(f"  ✅ {tool['name']:28s} — id={data['id'][:8]}... v{data.get('version', 1)}")
                elif resp.status_code == 409:
                    print(f"  ⚠️  {tool['name']:28s} — already exists")
                else:
                    print(f"  ❌ {tool['name']:28s} — {resp.status_code}: {resp.text[:80]}")
            except Exception as exc:
                print(f"  💥 {tool['name']:28s} — {exc}")


async def main():
    print("Seeding demo tools...\n")
    await register_all()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{BASE_URL}/tools")
        if resp.status_code == 200:
            tools = resp.json().get("items", [])
            print(f"\nTotal registered: {len(tools)}")
            for t in tools:
                print(f"  {t['name']}")
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
