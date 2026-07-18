"""Global pytest fixtures shared across all test categories.

Provides tenant/user UUIDs, sample tool payloads, mocked LLM client,
mocked EventBus, and other infrastructure shared by unit, integration,
contract, and eval tests.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.llm.client import LLMClient, LLMResponse, UsageInfo
from nexus.redis_client.pubsub import EventBus
from nexus.tools.schemas import ToolCreate, ToolExample

# ---------------------------------------------------------------------------
# Tenant & User
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def other_tenant_id() -> uuid.UUID:
    return uuid.UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.UUID("33333333-3333-4333-8333-333333333333")


@pytest.fixture
def session_id() -> uuid.UUID:
    return uuid.UUID("44444444-4444-4444-8444-444444444444")


# ---------------------------------------------------------------------------
# Sample Tool Payloads
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_tool_create() -> ToolCreate:
    return ToolCreate(
        name="echo",
        description="Echoes back the input",
        purpose="Testing tool execution pipeline",
        endpoint_url="http://localhost:9999/echo",
        http_method="POST",
        input_schema={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
        output_schema={
            "type": "object",
            "properties": {"echo": {"type": "string"}},
        },
        tags=["test", "core"],
        category="utilities",
        requires_approval=False,
        risk_level="low",
        enabled=True,
        examples=[
            ToolExample(
                user_prompt="Say hello",
                expected_tool="echo",
                sample_input={"msg": "hello"},
                sample_output={"echo": "hello"},
            )
        ],
    )


@pytest.fixture
def sample_tool_create_requires_approval() -> ToolCreate:
    return ToolCreate(
        name="delete_record",
        description="Deletes a database record",
        purpose="Destructive operation requiring approval",
        endpoint_url="http://localhost:9999/delete",
        http_method="DELETE",
        input_schema={
            "type": "object",
            "properties": {"record_id": {"type": "string"}},
            "required": ["record_id"],
        },
        output_schema={"type": "object", "properties": {"deleted": {"type": "boolean"}}},
        tags=["admin"],
        category="data",
        requires_approval=True,
        risk_level="high",
    )


@pytest.fixture
def sample_tools() -> list[ToolCreate]:
    return [
        ToolCreate(
            name="send_email",
            description="Send an email message",
            purpose="Send transactional or notification emails",
            endpoint_url="http://email-api/send",
            http_method="POST",
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject"],
            },
            tags=["communication"],
            category="notifications",
        ),
        ToolCreate(
            name="search_docs",
            description="Search internal documentation",
            purpose="Find relevant documents by keyword",
            endpoint_url="http://docs-api/search",
            http_method="GET",
            input_schema={
                "type": "object",
                "properties": {"q": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["q"],
            },
            tags=["search"],
            category="knowledge",
        ),
    ]


# ---------------------------------------------------------------------------
# Mocked LLM
# ---------------------------------------------------------------------------

_LLM_RESPONSE = LLMResponse(
    content="",
    usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    model="gpt-4o",
    provider="openai",
    latency_ms=100,
    cost_usd=0.001,
)


@pytest.fixture
def mocked_llm_client() -> MagicMock:
    """Return a MagicMock LLMClient with a canned response."""
    client = create_autospec(LLMClient, instance=True)
    client.complete = AsyncMock(return_value=_LLM_RESPONSE)
    client.embed = AsyncMock(return_value=[[0.1] * 768])
    return client


@pytest.fixture
def mocked_llm_response() -> LLMResponse:
    return _LLM_RESPONSE


# ---------------------------------------------------------------------------
# Mocked EventBus
# ---------------------------------------------------------------------------

@pytest.fixture
def mocked_event_bus() -> MagicMock:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


# ---------------------------------------------------------------------------
# Fake Redis
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fake_redis() -> AsyncGenerator[Redis, None]:
    redis = FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


# ---------------------------------------------------------------------------
# Tenant Context Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_tenant_context() -> None:
    """Clear tenant context between tests to avoid cross-test leakage."""
    from nexus.db.context import reset_tenant
    reset_tenant()


@pytest.fixture
def with_tenant(tenant_id: uuid.UUID) -> None:
    """Activate tenant context for the test scope."""
    from nexus.db.context import set_tenant
    set_tenant(tenant_id)
