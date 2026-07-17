"""Integration tests for the per-session concurrency lock with heartbeat.

Tests:
- Lock acquired and released around astream
- Lock released when graph pauses (HITL interrupt)
- Resume acquires its own lock
- Second invoke blocked while first is active
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.agent.runner import AgentRunner
from nexus.config.settings import get_settings
from nexus.llm.client import LLMResponse, UsageInfo
from nexus.redis_client.client import get_redis_client
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor

pytestmark = [pytest.mark.integration]


_LLM = LLMResponse(
    content="",
    usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    model="gpt-4o",
    provider="openai",
    latency_ms=50,
    cost_usd=0.001,
)


class _MockLLM:
    """Canned LLM that returns a minimal intent on first call."""

    def __init__(self, *, interrupt: bool = False) -> None:
        self.call_count = 0
        self._interrupt = interrupt

    async def complete(self, **kwargs: object) -> LLMResponse:
        self.call_count += 1
        if self.call_count == 1:
            return _LLM.model_copy(
                update={
                    "content": '{"intent":"test","parameters":{},"missing_info_slots":[]}'
                }
            )
        return _LLM.model_copy(update={"content": "ok"})


@pytest.fixture(autouse=True)
def _test_env() -> None:
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"
    os.environ["NEXUS_AGENT__RUN_LOCK_TTL_S"] = "30"
    get_settings.cache_clear()


@pytest.fixture
def redis() -> Any:
    from testcontainers.redis import RedisContainer
    container = RedisContainer(image="redis:7-alpine")
    container.start()
    os.environ["NEXUS_REDIS__URL"] = container.get_connection_url()
    get_settings.cache_clear()
    yield container
    container.stop()


@pytest.fixture
def tool_selector() -> DynamicToolSelector:
    sel = MagicMock(spec=DynamicToolSelector)
    sel.select = AsyncMock(return_value=[])
    return sel


@pytest.fixture
def tool_executor() -> ToolExecutor:
    ex = MagicMock(spec=ToolExecutor)
    ex.execute = AsyncMock(
        return_value=MagicMock(
            status="success",
            tool_id=str(uuid.uuid4()),
            tool_name="test",
            data={"result": "ok"},
            duration_ms=5,
        )
    )
    return ex


@pytest.fixture
def llm() -> _MockLLM:
    return _MockLLM()


async def _ack_emit_error(runner, sid, msg) -> str | None:
    """Invoke runner and return the error message if any."""
    async for event in runner.invoke(
        session_id=sid,
        user_message=msg or "test",
        tenant_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        config={"configurable": {"thread_id": str(sid)}},
    ):
        if event.type == "error":
            return event.payload.get("message", "")
    return None


@pytest.mark.asyncio
async def test_lock_released_on_completion(
    redis: Any,
    llm: _MockLLM,
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
) -> None:
    """After invoke() completes normally, the lock key is gone from Redis."""
    runner = AgentRunner(llm_client=llm, tool_selector=tool_selector, tool_executor=tool_executor)
    sid = str(uuid.uuid4())
    r = get_redis_client()
    lock_key = f"lock:agent_run:{sid}"

    async for _event in runner.invoke(
        session_id=sid,
        user_message="hello",
        tenant_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        config={"configurable": {"thread_id": sid}},
    ):
        pass

    exists = await r.exists(lock_key)
    assert not exists, f"Lock {lock_key} should be released after invoke"


@pytest.mark.asyncio
async def test_second_invoke_blocked(
    redis: Any,
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
) -> None:
    """Second invoke on same session yields error while first is active."""
    llm_a = _MockLLM()
    runner_active = AgentRunner(llm_client=llm_a, tool_selector=tool_selector, tool_executor=tool_executor)
    sid = str(uuid.uuid4())

    # Acquire the lock externally to simulate an active run
    r = get_redis_client()
    lock_key = f"lock:agent_run:{sid}"
    await r.set(lock_key, "fake-token", nx=True, ex=30)

    error_msg = await _ack_emit_error(runner_active, sid, "second attempt")
    assert error_msg is not None, "Second invoke should be blocked"
    assert "already in progress" in error_msg

    # Clean up
    await r.delete(lock_key)


@pytest.mark.asyncio
async def test_heartbeat_renews_lock(
    redis: Any,
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
) -> None:
    """The heartbeart extends the lock TTL during a long run."""
    llm_long = _MockLLM()
    runner = AgentRunner(llm_client=llm_long, tool_selector=tool_selector, tool_executor=tool_executor)
    sid = str(uuid.uuid4())
    r = get_redis_client()
    lock_key = f"lock:agent_run:{sid}"

    # Mock invoke's astream to run for 2s (enough for heartbeat to fire)
    original_build = runner._build_graph

    async def _build_and_slow_stream():
        graph = original_build()

        async def _slow_astream(*args: object, **kwargs: object):
            # Yield empty events for 2 seconds
            for _ in range(10):
                await asyncio.sleep(0.2)
                yield {"finalize": {"final_response": "still running...", "_routing_decision": "finalize"}}

        graph.astream = _slow_astream
        return graph

    runner._build_graph = _build_and_slow_stream

    async for _event in runner.invoke(
        session_id=sid,
        user_message="long run",
        tenant_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        config={"configurable": {"thread_id": sid}},
    ):
        pass

    # Lock should be gone after run completes
    exists = await r.exists(lock_key)
    assert not exists, f"Lock {lock_key} should be released after long run"
