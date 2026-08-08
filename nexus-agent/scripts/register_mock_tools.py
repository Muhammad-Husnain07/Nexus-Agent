"""Register mock tools into the Nexus Agent API using httpx."""
import asyncio

import httpx
import structlog

logger = structlog.get_logger("nexus.scripts.register_mock_tools")

NEXUS_API_URL = "http://localhost:8000/api/v1/tools"

TOOLS_TO_REGISTER = [
    {
        "name": "list_datasources",
        "description": "Fetches a list of available data sources (databases).",
        "purpose": "Use this first when a user wants to build a dashboard or query data.",
        "endpoint_url": "http://localhost:8001/datasources",
        "http_method": "GET",
        "tags": ["data", "database", "workflow"],
        "risk_level": "low",
    },
    {
        "name": "list_tables",
        "description": "Fetches tables for a specific datasource.",
        "purpose": "Use after list_datasources to find available tables.",
        "endpoint_url": "http://localhost:8001/datasources/{datasource}/tables",
        "http_method": "GET",
        "tags": ["data", "database", "workflow"],
        "input_schema": {
            "type": "object",
            "properties": {"datasource": {"type": "string"}},
            "required": ["datasource"],
        },
        "risk_level": "low",
    },
    {
        "name": "get_table_columns",
        "description": "Fetches schema/columns for a specific table.",
        "purpose": "Use to find out what data is available in a table.",
        "endpoint_url": "http://localhost:8001/tables/{table_name}/columns",
        "http_method": "GET",
        "tags": ["data", "database", "workflow"],
        "input_schema": {
            "type": "object",
            "properties": {"table_name": {"type": "string"}},
            "required": ["table_name"],
        },
        "risk_level": "low",
    },
    {
        "name": "query_table_data",
        "description": "Executes a query against a table to retrieve data rows.",
        "purpose": "Use to get the actual data for a report or dashboard.",
        "endpoint_url": "http://localhost:8001/query",
        "http_method": "POST",
        "tags": ["data", "database", "workflow"],
        "input_schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "columns": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["table", "columns"],
        },
        "risk_level": "medium",
    },
    {
        "name": "create_dashboard",
        "description": "Creates a new dashboard with specified widgets.",
        "purpose": "Use as the final step in a dashboard creation workflow.",
        "endpoint_url": "http://localhost:8001/dashboards",
        "http_method": "POST",
        "tags": ["artifact", "dashboard", "workflow"],
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "widgets": {"type": "array"},
            },
            "required": ["title", "widgets"],
        },
        "risk_level": "medium",
        "requires_approval": False,
    },
    {
        "name": "get_config",
        "description": "Retrieves a system configuration value.",
        "endpoint_url": "http://localhost:8001/config/{key}",
        "http_method": "GET",
        "tags": ["config"],
        "risk_level": "low",
    },
    {
        "name": "set_config",
        "description": "Updates a system configuration value.",
        "endpoint_url": "http://localhost:8001/config/{key}",
        "http_method": "POST",
        "tags": ["config"],
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {},
            },
            "required": ["key", "value"],
        },
        "risk_level": "high",
        "requires_approval": True,
    },
    {
        "name": "fetch_timeout_data",
        "description": "Fetches data from a notoriously slow external service.",
        "endpoint_url": "http://localhost:8001/error/timeout",
        "http_method": "GET",
        "tags": ["data", "error"],
        "risk_level": "low",
    },
    {
        "name": "fetch_unstable_data",
        "description": "Fetches data from an unstable service that returns 500s.",
        "endpoint_url": "http://localhost:8001/error/server",
        "http_method": "GET",
        "tags": ["data", "error"],
        "risk_level": "low",
    },
]


async def register():
    logger.info("register_mock_tools.start")
    async with httpx.AsyncClient() as client:
        for tool in TOOLS_TO_REGISTER:
            try:
                response = await client.post(NEXUS_API_URL, json=tool)
                response.raise_for_status()
                logger.info("register_mock_tools.success", tool=tool["name"])
            except httpx.HTTPStatusError as e:
                body = await e.response.aread()
                if b"already exists" in body.lower():
                    logger.warning("register_mock_tools.already_exists", tool=tool["name"])
                else:
                    logger.error("register_mock_tools.failed", tool=tool["name"], error=str(e))
            except Exception as e:
                logger.error("register_mock_tools.exception", tool=tool["name"], error=str(e))

    logger.info("register_mock_tools.complete")


if __name__ == "__main__":
    asyncio.run(register())
