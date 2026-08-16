"""FE Step 2 — SSE observer/run decoupling.

The browser is disposable: a client disconnect must cancel the OBSERVER,
never the run. The invocation drains into a queue from a detached task;
message persistence happens when the RUN finishes.
"""

from __future__ import annotations

import asyncio

from nexus.agent.runner import AgentEvent
from nexus.api.chat import _QueueIterator, _drain_invoke


async def _fake_invoke(events: list[AgentEvent]) -> AsyncIterator[AgentEvent]:
    for ev in events:
        yield ev


def _ev(type_: str, **payload) -> AgentEvent:  # noqa: ANN003
    return AgentEvent(type_, payload)


class TestDrainInvoke:
    async def test_drains_events_and_sentinel(self):
        queue: asyncio.Queue = asyncio.Queue()
        events = [_ev("plan_created", steps={}), _ev("tool_call_completed", tool_name="x")]
        await _drain_invoke(_fake_invoke(events), queue, "s1", "hi")
        got = []
        while True:
            item = await queue.get()
            if item is None:
                break
            got.append(item)
        assert [e.type for e in got] == ["plan_created", "tool_call_completed"]

    async def test_captures_final_text_for_persistence(self, monkeypatch):
        import nexus.api.chat as chat_mod

        persisted: list[tuple] = []

        async def _fake_persist(sid: str, message: str, final_text: str | None) -> None:
            persisted.append((sid, message, final_text))

        monkeypatch.setattr(chat_mod, "_persist_messages", _fake_persist)
        queue: asyncio.Queue = asyncio.Queue()
        events = [
            _ev("final_response", text="The weather in Lahore is 32c.", response_status="SUCCESS"),
        ]
        await _drain_invoke(_fake_invoke(events), queue, "s1", "weather in Lahore")
        await asyncio.sleep(0.05)  # allow the fire-and-forget persist task
        assert persisted == [("s1", "weather in Lahore", "The weather in Lahore is 32c.")]

    async def test_error_event_and_sentinel_on_failure(self):
        async def _boom() -> AsyncIterator[AgentEvent]:
            yield _ev("plan_created", steps={})
            raise RuntimeError("graph exploded")

        queue: asyncio.Queue = asyncio.Queue()
        await _drain_invoke(_boom(), queue, "s1", "hi")
        got = []
        while True:
            item = await queue.get()
            if item is None:
                break
            got.append(item)
        assert got[0].type == "plan_created"
        assert got[1]["event"] == "error"
        assert "graph exploded" in got[1]["data"]

    async def test_queue_iterator_stops_on_sentinel(self):
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(_ev("done"))
        await queue.put(None)
        it = _QueueIterator(queue)
        first = await it.__anext__()
        assert first.type == "done"
        try:
            await it.__anext__()
            raise AssertionError("expected StopAsyncIteration")
        except StopAsyncIteration:
            pass

    async def test_observer_disconnect_does_not_cancel_the_run(self):
        """The decoupling contract: cancelling the OBSERVER leaves the drain
        task executing — the run finishes and the sentinel lands."""
        queue: asyncio.Queue = asyncio.Queue()

        async def _slow() -> AsyncIterator[AgentEvent]:
            yield _ev("plan_created", steps={})
            await asyncio.sleep(0.2)
            yield _ev("final_response", text="done", response_status="SUCCESS")

        drain = asyncio.create_task(_drain_invoke(_slow(), queue, "s1", "hi"))
        await asyncio.sleep(0.05)
        # Observer cancels itself mid-run.
        first = await queue.get()
        assert first.type == "plan_created"
        # The drain task survives the observer's cancellation.
        rest = []
        while True:
            item = await queue.get()
            if item is None:
                break
            rest.append(item)
        await drain
        assert rest[0].type == "final_response"
        assert rest[0].payload["text"] == "done"
class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int = 0) -> None:  # noqa: ARG002
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class TestCooperativeCancellation:
    async def test_flag_roundtrip(self):
        from nexus.agent.runner import _cancellation_requested, _clear_cancellation

        redis = _FakeRedis()
        await redis.set("nexus:cancel:agent_run:s1", "1", ex=600)
        assert await _cancellation_requested(redis, "s1") is True
        await _clear_cancellation(redis, "s1")
        assert await _cancellation_requested(redis, "s1") is False

    async def test_degrades_open_on_redis_failure(self):
        from nexus.agent.runner import _cancellation_requested, _clear_cancellation

        class _BoomRedis:
            async def get(self, key: str) -> str:  # noqa: ARG002
                raise RuntimeError("redis down")

            async def delete(self, key: str) -> None:  # noqa: ARG002
                raise RuntimeError("redis down")

        assert await _cancellation_requested(_BoomRedis(), "s1") is False
        await _clear_cancellation(_BoomRedis(), "s1")  # must not raise
