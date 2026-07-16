"""Unit tests for the Redis pub/sub EventBus."""

from __future__ import annotations

import asyncio

import pytest_asyncio

from nexus.redis_client.pubsub import (
    EventBus,
    agent_channel,
    tool_channel,
)


@pytest_asyncio.fixture
async def bus(fake_redis):
    return EventBus(fake_redis)


async def test_publish_and_subscribe(bus, fake_redis) -> None:
    channel = agent_channel("sess-1")
    received: list[dict] = []
    sub_task = asyncio.create_task(_collect(bus, channel, received, count=1))
    # Give the subscriber time to connect
    await asyncio.sleep(0.05)
    await bus.publish(channel, {"type": "token", "text": "hi"})
    await asyncio.wait_for(sub_task, timeout=2.0)

    assert len(received) == 1
    event = received[0]
    assert event["type"] == "token"
    assert event["payload"]["text"] == "hi"
    assert "ts" in event


async def test_multiple_subscribers_same_channel(bus, fake_redis) -> None:
    channel = tool_channel("sess-2")
    r1: list[dict] = []
    r2: list[dict] = []
    t1 = asyncio.create_task(_collect(bus, channel, r1, count=1))
    t2 = asyncio.create_task(_collect(bus, channel, r2, count=1))
    await asyncio.sleep(0.05)
    await bus.publish(channel, {"type": "tool_result", "ok": True})
    await asyncio.wait_for(asyncio.gather(t1, t2), timeout=2.0)

    assert len(r1) == 1
    assert len(r2) == 1
    assert r1[0]["payload"]["ok"] is True


async def test_different_channels_isolated(bus, fake_redis) -> None:
    ch_a = agent_channel("sess-a")
    ch_b = agent_channel("sess-b")
    ra: list[dict] = []
    rb: list[dict] = []
    ta = asyncio.create_task(_collect(bus, ch_a, ra, count=1))
    tb = asyncio.create_task(_collect(bus, ch_b, rb, count=1))
    await asyncio.sleep(0.05)
    await bus.publish(ch_a, {"type": "a"})
    await bus.publish(ch_b, {"type": "b"})
    await asyncio.wait_for(asyncio.gather(ta, tb), timeout=2.0)

    assert ra[0]["type"] == "a"
    assert rb[0]["type"] == "b"


async def _collect(bus, channel: str, sink: list[dict], count: int) -> None:
    """Collect ``count`` events from ``channel`` into ``sink``."""
    async for event in bus.subscribe(channel):
        sink.append(event)
        if len(sink) >= count:
            break
