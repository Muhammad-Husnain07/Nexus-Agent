"""Unit tests for the PostgresSaver checkpointer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from nexus.memory.checkpointer import close_checkpointer, create_pool, get_checkpointer


class TestCheckpointer:
    """PostgresSaver checkpointer."""

    async def test_create_pool_rewrites_url(self) -> None:
        with patch("nexus.memory.checkpointer.get_settings") as mock_settings:
            mock_settings.return_value.database.url = "postgresql+asyncpg://u:p@h:5432/db"
            mock_settings.return_value.database.pool_size = 5
            with patch("nexus.memory.checkpointer.AsyncConnectionPool") as mock_pool:
                create_pool()
                assert mock_pool.called
                url_arg = mock_pool.call_args[0][0]
                assert "postgresql://" in url_arg
                assert "+asyncpg" not in url_arg

    async def test_get_checkpointer_creates_singleton(self) -> None:
        mock_saver = MagicMock()
        mock_saver.setup = AsyncMock()
        mock_conn = MagicMock()

        with (
            patch("nexus.memory.checkpointer.create_pool") as mock_create_pool,
            patch("nexus.memory.checkpointer.PostgresSaver", return_value=mock_saver) as mock_saver_cls,
        ):
            mock_pool = MagicMock()
            mock_pool.connection = AsyncMock(return_value=mock_conn)
            mock_create_pool.return_value = mock_pool

            saver1 = await get_checkpointer()
            saver2 = await get_checkpointer()

            assert saver1 is saver2
            mock_saver_cls.assert_called_once_with(conn=mock_conn)
            mock_saver.setup.assert_awaited_once()

    async def test_close_checkpointer(self) -> None:
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        mock_conn = MagicMock()
        mock_conn.pool = mock_pool
        mock_saver = MagicMock()
        mock_saver.conn = mock_conn

        with patch("nexus.memory.checkpointer._checkpointer", mock_saver):
            await close_checkpointer()
            mock_pool.close.assert_awaited_once()
