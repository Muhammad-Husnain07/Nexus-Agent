"""Register the 15 live test tools (idempotent — skips existing names).

Corrected/verified endpoints:
- get_country_info → Wikipedia REST summary (restcountries.com v1–v4 are
  decommissioned; v5 requires an API key).
- jsonplaceholder_request → GET-only (one tool = one method).
All schemas were validated against live responses.
"""

from __future__ import annotations

import json
import urllib.request

BASE = "http://localhost:8000/api/v1/tools"

TOOLS: list[dict] = [
    {
        "name": "reverse_geocode",
        "description": "Convert latitude/longitude into a human-readable OpenStreetMap address.",
        "purpose": "Use when the user gives coordinates and wants an address, or asks 'where am I' with a location.",
        "endpoint_url": "https://nominatim.openstreetmap.org/reverse?lat={latitude}&lon={longitude}&format=jsonv2",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["latitude", "longitude"],
            "properties": {
                "latitude": {"type": "number", "x-aliases": ["lat"], "description": "Latitude"},
                "longitude": {"type": "number", "x-aliases": ["lon", "lng"], "description": "Longitude"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "display_name": {"type": "string"},
                "type": {"type": "string"},
                "lat": {"type": "string"},
                "lon": {"type": "string"},
                "address": {"type": "object"},
            },
            "x-artifact-fields": {
                "place_name": "display_name",
                "place_type": "type",
            },
        },
        "examples": [
            {"user_prompt": "What address is at 31.55,74.34?", "expected_tool": "reverse_geocode", "sample_input": {"latitude": 31.55, "longitude": 74.34}}
        ],
        "tags": ["reverse_geocoding", "maps", "coordinates", "address", "location", "openstreetmap", "nominatim"],
        "category": "maps",
        "keywords": ["reverse geocode", "address from coordinates", "lat lon", "address lookup", "where am i"],
        "aliases": ["reverse geocode", "coordinates to address", "location lookup"],
        "capabilities": ["retrieve", "reverse_geocoding", "maps"],
        "produces": ["address", "display_name", "location_details"],
        "consumes": ["latitude", "longitude"],
        "cacheable": False,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "search_products",
        "description": "Retrieve the full product catalog from the Fake Store API.",
        "purpose": "Use when the user wants to browse the product catalog, product prices, or product categories. For a SPECIFIC product id use get_product; for a category use get_products_by_category.",
        "endpoint_url": "https://fakestoreapi.com/products",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "price": {"type": "number"},
                    "category": {"type": "string"},
                    "description": {"type": "string"},
                    "rating": {"type": "object"},
                },
            },
        },
        "examples": [
            {"user_prompt": "Show me the products", "expected_tool": "search_products", "sample_input": {}}
        ],
        "tags": ["ecommerce", "products", "shopping", "fakestore"],
        "category": "ecommerce",
        "keywords": ["products", "store", "shop", "item", "catalog", "product catalog"],
        "aliases": ["browse products", "product catalog", "list products"],
        "capabilities": ["retrieve", "products"],
        "produces": ["product_list"],
        "consumes": [],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "get_exchange_rates",
        "description": "Retrieve latest currency exchange rates for a base currency.",
        "purpose": "Use when the user asks about currency exchange rates, conversion between currencies, or forex rates.",
        "endpoint_url": "https://open.er-api.com/v6/latest/{base_currency}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["base_currency"],
            "properties": {
                "base_currency": {"type": "string", "x-aliases": ["currency", "from"], "description": "Base currency code (e.g. USD)"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "base_code": {"type": "string"},
                "rates": {"type": "object"},
                "time_last_update_unix": {"type": "integer"},
            },
        },
        "examples": [
            {"user_prompt": "What is the USD to EUR exchange rate?", "expected_tool": "get_exchange_rates", "sample_input": {"base_currency": "USD"}}
        ],
        "tags": ["currency", "exchange", "forex", "rates"],
        "category": "finance",
        "keywords": ["usd eur exchange", "currency conversion", "exchange rate", "forex"],
        "aliases": ["exchange rates", "currency rates"],
        "capabilities": ["retrieve", "finance"],
        "produces": ["exchange_rates"],
        "consumes": ["base_currency"],
        "cacheable": False,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "get_country_info",
        "description": "Retrieve a Wikipedia summary for a country, including general description and any facts the summary mentions (such as capital or population).",
        "purpose": "Use when the user asks for a general country overview or a Wikipedia-style summary of a country. The output is the Wikipedia page summary text — it does NOT guarantee structured or current population/capital data.",
        "endpoint_url": "https://en.wikipedia.org/api/rest_v1/page/summary/{country}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["country"],
            "properties": {
                "country": {"type": "string", "x-aliases": ["name", "nation"], "description": "Country name"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "extract": {"type": "string"},
                "description": {"type": "string"},
                "pageid": {"type": "integer"},
            },
        },
        "examples": [
            {"user_prompt": "Tell me about Pakistan", "expected_tool": "get_country_info", "sample_input": {"country": "Pakistan"}}
        ],
        "tags": ["geography", "country", "countries", "wikipedia"],
        "category": "geography",
        "keywords": ["country info", "country facts", "capital", "population"],
        "aliases": ["country info", "country facts"],
        "capabilities": ["retrieve", "geography"],
        "produces": ["country_details", "country_summary"],
        "consumes": ["country"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "search_universities",
        "description": "Search universities by name via the Hipolabs API.",
        "purpose": "Use when the user asks about universities, colleges, or higher education institutions.",
        "endpoint_url": "https://universities.hipolabs.com/search?name={name}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "x-aliases": ["university", "university name"], "description": "University name to search"},
            },
        },
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "country": {"type": "string"},
                    "domains": {"type": "array"},
                    "web_pages": {"type": "array"},
                    "alpha_two_code": {"type": "string"},
                },
            },
        },
        "examples": [
            {"user_prompt": "Find universities in Japan called Waseda", "expected_tool": "search_universities", "sample_input": {"name": "Waseda"}}
        ],
        "tags": ["education", "universities", "colleges"],
        "category": "education",
        "keywords": ["universities", "university", "college", "higher education"],
        "aliases": ["find universities", "university search"],
        "capabilities": ["retrieve", "education"],
        "produces": ["university_list", "country"],
        "consumes": ["name"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "get_ghibli_films",
        "description": "Retrieve Studio Ghibli films from the Ghibli API.",
        "purpose": "Use when the user asks about Studio Ghibli films, movies, directors, or ratings.",
        "endpoint_url": "https://ghibliapi.vercel.app/films",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "director": {"type": "string"},
                    "release_date": {"type": "string"},
                    "rt_score": {"type": "string"},
                },
            },
        },
        "examples": [
            {"user_prompt": "List Studio Ghibli films", "expected_tool": "get_ghibli_films", "sample_input": {}}
        ],
        "tags": ["movies", "ghibli", "animation"],
        "category": "entertainment",
        "keywords": ["ghibli", "studio ghibli", "anime films", "movies"],
        "aliases": ["ghibli films", "studio ghibli movies"],
        "capabilities": ["retrieve", "entertainment"],
        "produces": ["film_list"],
        "consumes": [],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "define_word",
        "description": "Get definitions, pronunciation, and meanings for an English word.",
        "purpose": "Use when the user asks for the definition or meaning of a word.",
        "endpoint_url": "https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["word"],
            "properties": {
                "word": {"type": "string", "x-aliases": ["term", "define"], "description": "Word to define"},
            },
        },
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "phonetics": {"type": "array"},
                    "meanings": {"type": "array"},
                    "origin": {"type": "string"},
                },
            },
        },
        "examples": [
            {"user_prompt": "Define the word analytics", "expected_tool": "define_word", "sample_input": {"word": "analytics"}}
        ],
        "tags": ["dictionary", "definitions", "language"],
        "category": "language",
        "keywords": ["define", "definition", "meaning", "dictionary", "word meaning"],
        "aliases": ["define word", "word meaning", "what does it mean"],
        "capabilities": ["retrieve", "language"],
        "produces": ["definition", "word_meaning"],
        "consumes": ["word"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "search_meals",
        "description": "Search meals and recipes from TheMealDB.",
        "purpose": "Use when the user asks about meals, recipes, or cooking ingredients.",
        "endpoint_url": "https://www.themealdb.com/api/json/v1/1/search.php?s={query}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "x-aliases": ["meal", "recipe", "search"], "description": "Meal or recipe name"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "meals": {
                    "type": ["array", "null"],
                    "items": {
                        "type": "object",
                        "properties": {
                            "idMeal": {"type": ["string", "null"]},
                            "strMeal": {"type": ["string", "null"]},
                            "strCategory": {"type": ["string", "null"]},
                            "strArea": {"type": ["string", "null"]},
                            "strInstructions": {"type": ["string", "null"]},
                        },
                    },
                    # TheMealDB returns {"meals": null} for no-match and
                    # null item fields for partial records — legitimate
                    # empty results, never failures.
                    "x-artifact-optional": True,
                }
            },
        },
        "examples": [
            {"user_prompt": "Search for chicken recipes", "expected_tool": "search_meals", "sample_input": {"query": "chicken"}}
        ],
        "tags": ["food", "recipes", "meals", "cooking"],
        "category": "food",
        "keywords": ["recipes", "meals", "cooking", "food"],
        "aliases": ["search recipes", "find meals"],
        "capabilities": ["retrieve", "food"],
        "produces": ["meal_list", "recipe"],
        "consumes": ["query"],
        "cacheable": False,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "search_anime",
        "description": "Search anime on AniList via GraphQL (title, score, episodes, format).",
        "purpose": "Use when the user asks about anime titles, scores, episodes, or anime search.",
        "endpoint_url": "https://graphql.anilist.co",
        "http_method": "POST",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["search"],
            "properties": {
                "search": {"type": "string", "x-aliases": ["title", "anime", "query"], "description": "Anime title to search"},
                "page": {"type": "integer", "default": 1, "description": "Result page"},
            },
            "x-graphql-query": (
                "query ($search: String, $page: Int) {"
                "  Page(page: $page, perPage: 5) {"
                "    media(search: $search, type: ANIME) {"
                "      id"
                "      title { romaji english native }"
                "      averageScore"
                "      episodes"
                "      format"
                "    }"
                "  }"
                "}"
            ),
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "Page": {
                            "type": "object",
                            "properties": {
                                "media": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "title": {"type": "object"},
                                            "averageScore": {"type": ["integer", "null"]},
                                            "episodes": {"type": ["integer", "null"]},
                                            "format": {"type": ["string", "null"]},
                                        },
                                    },
                                }
                            },
                        }
                    },
                }
            },
        },
        "examples": [
            {"user_prompt": "Search for the anime Naruto", "expected_tool": "search_anime", "sample_input": {"search": "Naruto"}}
        ],
        "tags": ["anime", "anilist", "graphql", "entertainment"],
        "category": "entertainment",
        "keywords": ["anime", "anime search", "anilist"],
        "aliases": ["search anime", "anime lookup"],
        "capabilities": ["retrieve", "entertainment"],
        "produces": ["anime_list"],
        "consumes": ["search"],
        "cacheable": False,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "search_manga",
        "description": "Search manga on AniList via GraphQL (title, score, chapters, format).",
        "purpose": "Use when the user asks about manga titles, scores, chapters, or manga search.",
        "endpoint_url": "https://graphql.anilist.co",
        "http_method": "POST",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["search"],
            "properties": {
                "search": {"type": "string", "x-aliases": ["title", "manga", "query"], "description": "Manga title to search"},
                "page": {"type": "integer", "default": 1, "description": "Result page"},
            },
            "x-graphql-query": (
                "query ($search: String, $page: Int) {"
                "  Page(page: $page, perPage: 5) {"
                "    media(search: $search, type: MANGA) {"
                "      id"
                "      title { romaji english native }"
                "      averageScore"
                "      chapters"
                "      format"
                "    }"
                "  }"
                "}"
            ),
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "Page": {
                            "type": "object",
                            "properties": {
                                "media": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "title": {"type": "object"},
                                            "averageScore": {"type": ["integer", "null"]},
                                            "chapters": {"type": ["integer", "null"]},
                                            "format": {"type": ["string", "null"]},
                                        },
                                    },
                                }
                            },
                        }
                    },
                }
            },
        },
        "examples": [
            {"user_prompt": "Search for the manga One Piece", "expected_tool": "search_manga", "sample_input": {"search": "One Piece"}}
        ],
        "tags": ["manga", "anilist", "graphql", "entertainment"],
        "category": "entertainment",
        "keywords": ["manga", "manga search", "anilist"],
        "aliases": ["search manga", "manga lookup"],
        "capabilities": ["retrieve", "entertainment"],
        "produces": ["manga_list"],
        "consumes": ["search"],
        "cacheable": False,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "get_valorant_agents",
        "description": "Retrieve Valorant agents from the Valorant API.",
        "purpose": "Use when the user asks about Valorant agents, their abilities, or descriptions.",
        "endpoint_url": "https://valorant-api.com/v1/agents",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "integer"},
                "data": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "uuid": {"type": "string"},
                            "displayName": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                },
            },
        },
        "examples": [
            {"user_prompt": "List Valorant agents", "expected_tool": "get_valorant_agents", "sample_input": {}}
        ],
        "tags": ["valorant", "gaming", "agents"],
        "category": "gaming",
        "keywords": ["valorant", "valorant agents", "agents"],
        "aliases": ["valorant agents", "valorant roster"],
        "capabilities": ["retrieve", "gaming"],
        "produces": ["agent_list"],
        "consumes": [],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "search_books",
        "description": "Search books from Gutendex (Project Gutenberg).",
        "purpose": "Use when the user asks to search books, titles, or literature.",
        "endpoint_url": "https://gutendex.com/books?search={query}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "x-aliases": ["title", "book", "search"], "description": "Book title or search text"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "title": {"type": "string"},
                            "authors": {"type": "array"},
                        },
                    },
                },
            },
        },
        "examples": [
            {"user_prompt": "Search books by Pride and Prejudice", "expected_tool": "search_books", "sample_input": {"query": "Pride and Prejudice"}}
        ],
        "tags": ["books", "literature", "gutenberg"],
        "category": "books",
        "keywords": ["books", "book search", "literature", "novels"],
        "aliases": ["search books", "find books"],
        "capabilities": ["retrieve", "books"],
        "produces": ["book_list", "book"],
        "consumes": ["query"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "search_authors",
        "description": "Search books by author from Gutendex (Project Gutenberg).",
        "purpose": "Use when the user wants to find books by a specific author.",
        "endpoint_url": "https://gutendex.com/books?search={author}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["author"],
            "properties": {
                "author": {"type": "string", "x-aliases": ["name", "writer"], "description": "Author name to search"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "title": {"type": "string"},
                            "authors": {"type": "array"},
                        },
                    },
                },
            },
        },
        "examples": [
            {"user_prompt": "Find books by Jane Austen", "expected_tool": "search_authors", "sample_input": {"author": "Jane Austen"}}
        ],
        "tags": ["books", "authors", "literature"],
        "category": "books",
        "keywords": ["books by author", "authors", "writer"],
        "aliases": ["search by author", "books by"],
        "capabilities": ["retrieve", "books"],
        "produces": ["book_list"],
        "consumes": ["author"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "get_docker_images",
        "description": "Retrieve Docker Hub image information for a repository.",
        "purpose": "Use when the user asks about Docker images, pulls, stars, or repository info.",
        "endpoint_url": "https://hub.docker.com/v2/repositories/{namespace}/{repository}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["repository"],
            "properties": {
                "namespace": {"type": "string", "default": "library", "x-aliases": ["org", "owner"], "description": "Docker namespace/org (defaults to library for official images)"},
                "repository": {"type": "string", "x-aliases": ["image", "repo"], "description": "Repository name (e.g. nginx)"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "user": {"type": "string"},
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "description": {"type": "string"},
                "star_count": {"type": "integer"},
                "pull_count": {"type": "integer"},
                "last_updated": {"type": "string"},
            },
            "x-artifact-fields": {
                "stars": "star_count",
                "image_description": "description",
                "namespace": "namespace",
                "image_name": "name",
                "pull_count": "pull_count",
            },
        },
        "examples": [
            {"user_prompt": "How many pulls does the nginx docker image have?", "expected_tool": "get_docker_images", "sample_input": {"namespace": "library", "repository": "nginx"}}
        ],
        "tags": ["docker", "containers", "devops"],
        "category": "devops",
        "keywords": ["docker", "docker image", "docker pulls", "container"],
        "aliases": ["docker image info", "docker pulls"],
        "capabilities": ["retrieve", "devops"],
        "produces": ["docker_image_info"],
        "consumes": ["namespace", "repository"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "jsonplaceholder_request",
        "description": "Fake REST API for testing CRUD-style reads (GET).",
        "purpose": "Use when the user wants sample posts, todos, users, or comments from the JSONPlaceholder test API. Read-only GET.",
        "endpoint_url": "https://jsonplaceholder.typicode.com/{resource}/{id}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "properties": {
                "resource": {"type": "string", "default": "posts", "x-aliases": ["endpoint"], "description": "Resource name: posts, todos, users, comments"},
                "id": {"type": "integer", "x-aliases": ["post_id"], "description": "Optional record id"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "userId": {"type": "integer"},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
        },
        "examples": [
            {"user_prompt": "Fetch post 1 from jsonplaceholder", "expected_tool": "jsonplaceholder_request", "sample_input": {"resource": "posts", "id": 1}}
        ],
        "tags": ["jsonplaceholder", "testing", "crud", "mock"],
        "category": "testing",
        "keywords": ["jsonplaceholder", "sample data", "mock api", "test api"],
        "aliases": ["json placeholder", "sample posts"],
        "capabilities": ["retrieve", "testing"],
        "produces": ["mock_data"],
        "consumes": ["resource", "id"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "search_web_search",
        "description": "Search the web index served by the local mock search server.",
        "purpose": "Use when the user asks for web search results, news, or general web information.",
        "endpoint_url": "http://localhost:8081/search",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["q"],
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "default": 5, "description": "Max results"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "results": {"type": "array"},
                "query": {"type": "string"},
            },
        },
        "examples": [
            {"user_prompt": "search for books about climate", "expected_tool": "web_search", "sample_input": {"q": "books about climate"}}
        ],
        "tags": ["web", "search", "mock"],
        "category": "general",
        "keywords": ["web search", "search the web", "find on the internet"],
        "aliases": ["web_search", "web search", "search", "internet search"],
        "capabilities": ["retrieve", "search"],
        "produces": ["search_results"],
        "consumes": ["q", "max_results"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "get_product",
        "description": "Retrieve a single product by id from the Fake Store API.",
        "purpose": "Use when the user asks about a SPECIFIC product id (e.g. product 1). For the full catalog use search_products; for a category use get_products_by_category.",
        "endpoint_url": "https://fakestoreapi.com/products/{id}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "integer", "x-aliases": ["product id", "product"], "description": "Product id"},
            },
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "price": {"type": "number"},
                "category": {"type": "string"},
                "description": {"type": "string"},
                "rating": {"type": "object"},
            },
        },
        "examples": [
            {"user_prompt": "Get product 1 from the store", "expected_tool": "get_product", "sample_input": {"id": 1}}
        ],
        "tags": ["ecommerce", "products", "fakestore"],
        "category": "ecommerce",
        "keywords": ["product detail", "product by id"],
        "aliases": ["get product", "product detail"],
        "capabilities": ["retrieve", "products"],
        "produces": ["product"],
        "consumes": ["id"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
    {
        "name": "get_products_by_category",
        "description": "Retrieve products in a category from the Fake Store API.",
        "purpose": "Use when the user asks for products in a SPECIFIC category (e.g. electronics, jewelry). For the full catalog use search_products; for a specific id use get_product.",
        "endpoint_url": "https://fakestoreapi.com/products/category/{category}",
        "http_method": "GET",
        "auth_type": "none",
        "input_schema": {
            "type": "object",
            "required": ["category"],
            "properties": {
                "category": {"type": "string", "x-aliases": ["product category"], "description": "Product category (e.g. electronics, jewelry, men's clothing)"},
            },
        },
        "output_schema": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "price": {"type": "number"},
                    "category": {"type": "string"},
                    "description": {"type": "string"},
                    "rating": {"type": "object"},
                },
            },
        },
        "examples": [
            {"user_prompt": "Show me products in the electronics category", "expected_tool": "get_products_by_category", "sample_input": {"category": "electronics"}}
        ],
        "tags": ["ecommerce", "products", "fakestore"],
        "category": "ecommerce",
        "keywords": ["products in category", "category products"],
        "aliases": ["products by category", "category catalog"],
        "capabilities": ["retrieve", "products"],
        "produces": ["product_list"],
        "consumes": ["category"],
        "cacheable": True,
        "idempotent": True,
        "enabled": True,
    },
]


def register(tool: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        BASE,
        data=json.dumps(tool).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read().decode())
            return 201, body.get("name", "?")
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:120]
        return e.code, detail


def main() -> None:
    ok = dup = failed = 0
    for tool in TOOLS:
        code, msg = register(tool)
        if code == 201:
            ok += 1
            print(f"  ✓ {tool['name']}")
        elif code == 409:
            dup += 1
            print(f"  = {tool['name']} (already exists)")
        else:
            failed += 1
            print(f"  ✗ {tool['name']} -> {code} {msg}")
    print(f"\nregistered={ok} existing={dup} failed={failed}")


if __name__ == "__main__":
    main()
