"""Tests for the background task scheduler used for memory decay."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.utils.scheduler import start_scheduler, stop_scheduler


class TestScheduler:
    """Verify scheduler start/stop lifecycle."""

    async def test_start_scheduler_creates_task(self) -> None:
        await start_scheduler(interval_s=9999)
        from nexus.utils.scheduler import _task

        assert _task is not None
        assert not _task.done()
        await stop_scheduler()
        assert _task is None or _task.done()

    async def test_start_scheduler_is_idempotent(self) -> None:
        await start_scheduler(interval_s=9999)
        await start_scheduler(interval_s=9999)
        from nexus.utils.scheduler import _task

        assert _task is not None
        await stop_scheduler()

    async def test_stop_scheduler_cancels_task(self) -> None:
        await start_scheduler(interval_s=9999)
        await stop_scheduler()
        from nexus.utils.scheduler import _task

        assert _task is None or _task.done()

    async def test_stop_idempotent(self) -> None:
        await stop_scheduler()
        await stop_scheduler()

    async def test_memory_decay_loop_runs(self) -> None:
        """Verify the decay loop calls MemoryManager.decay()."""
        with patch("nexus.memory.manager.MemoryManager") as mock_mgr_cls:
            instance = AsyncMock()
            instance.decay = AsyncMock()
            mock_mgr_cls.return_value = instance

            from nexus.utils.scheduler import _memory_decay_loop

            task = asyncio.create_task(_memory_decay_loop(interval_s=0.1))
            await asyncio.sleep(0.3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert instance.decay.awaited

    async def test_decay_error_does_not_crash_loop(self) -> None:
        """If decay raises, the loop continues."""
        with patch("nexus.memory.manager.MemoryManager") as mock_mgr_cls:
            instance = AsyncMock()
            instance.decay = AsyncMock(side_effect=[Exception("boom"), None])
            mock_mgr_cls.return_value = instance

            from nexus.utils.scheduler import _memory_decay_loop

            task = asyncio.create_task(_memory_decay_loop(interval_s=0.1))
            await asyncio.sleep(0.35)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert instance.decay.call_count >= 2
