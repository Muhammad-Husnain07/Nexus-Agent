"""Unit tests for the AsyncPostgresSaver checkpointer."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.memory.checkpointer import close_checkpointer, get_checkpointer


class TestCheckpointer:
    """AsyncPostgresSaver checkpointer."""

    @pytest.mark.skipif(sys.platform == "win32", reason="pgvector/psycopg not available on Windows")
    async def test_get_checkpointer_creates_singleton(self) -> None:
        mock_saver = MagicMock()
        mock_saver.setup = AsyncMock()
        mock_conn = MagicMock()

        with (
            patch("nexus.memory.checkpointer.AsyncConnectionPool") as mock_pool_cls,
            patch("nexus.memory.checkpointer.AsyncPostgresSaver", return_value=mock_saver) as mock_saver_cls,
        ):
            mock_pool = MagicMock()
            mock_conn_cm = MagicMock()
            mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.connection.return_value = mock_conn_cm
            mock_pool_cls.return_value = mock_pool

            saver1 = await get_checkpointer()
            saver2 = await get_checkpointer()

            assert saver1 is saver2
            mock_saver_cls.assert_called_once_with(conn=mock_conn)
            mock_saver.setup.assert_awaited_once()
            assert mock_conn.autocommit is True

    async def test_get_checkpointer_returns_none_on_windows(self) -> None:
        """On Windows, get_checkpointer returns None."""
        if sys.platform == "win32":
            result = await get_checkpointer()
            assert result is None

    async def test_close_checkpointer(self) -> None:
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()

        with (
            patch("nexus.memory.checkpointer._checkpointer", MagicMock()),
            patch("nexus.memory.checkpointer._pool", mock_pool),
        ):
            await close_checkpointer()
            mock_pool.close.assert_awaited_once()
