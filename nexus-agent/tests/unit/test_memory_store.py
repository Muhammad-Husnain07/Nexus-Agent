"""Unit tests for MemoryStore with mocked DB."""

# ruff: noqa: SIM117, E501

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.memory.store import MemoryStore


class TestMemoryStore:
    """MemoryStore — put, get, search, delete."""

    @pytest.fixture
    def store(self) -> MemoryStore:
        return MemoryStore()

    @pytest.fixture
    def namespace(self) -> tuple[str, str, str]:
        return ("00000000-0000-0000-0000-000000000001", "memories", "preference")

    async def test_put_creates_new(self, store: MemoryStore, namespace: tuple[str, str, str]) -> None:
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo.create = AsyncMock()

        with patch("nexus.memory.store.async_session"):
            with patch("nexus.memory.store.TenantScopedRepository", return_value=mock_repo):
                mid = await store.put(
                    namespace=namespace,
                    content="User prefers dark mode",
                    importance=0.8,
                )

        assert isinstance(mid, uuid.UUID)
        mock_repo.create.assert_awaited_once()

    async def test_put_updates_existing(self, store: MemoryStore, namespace: tuple[str, str, str]) -> None:
        existing_id = uuid.uuid4()
        existing_mem = MagicMock()
        existing_mem.id = existing_id

        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=existing_mem)
        mock_repo.create = MagicMock()

        with patch("nexus.memory.store.async_session"):
            with patch("nexus.memory.store.TenantScopedRepository", return_value=mock_repo):
                mid = await store.put(
                    namespace=namespace,
                    memory_id=existing_id,
                    content="Updated preference",
                    importance=0.9,
                )

        assert mid == existing_id
        assert existing_mem.content == "Updated preference"
        assert existing_mem.importance == 0.9

    async def test_get_returns_none_for_missing(self, store: MemoryStore) -> None:
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=None)

        with patch("nexus.memory.store.async_session"):
            with patch("nexus.memory.store.TenantScopedRepository", return_value=mock_repo):
                result = await store.get(("tid", "memories", "fact"), uuid.uuid4())

        assert result is None

    async def test_get_returns_row(self, store: MemoryStore) -> None:
        mem_id = uuid.uuid4()
        mock_mem = MagicMock()
        mock_mem.id = mem_id
        mock_mem.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        mock_mem.session_id = None
        mock_mem.kind = "preference"
        mock_mem.content = "User likes dark mode"
        mock_mem.metadata_ = {"user_id": "u1"}
        mock_mem.importance = 0.8
        mock_mem.created_at = None
        mock_mem.last_accessed_at = None

        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_mem)

        with patch("nexus.memory.store.async_session"):
            with patch("nexus.memory.store.TenantScopedRepository", return_value=mock_repo):
                result = await store.get(("tid", "memories", "preference"), mem_id)

        assert result is not None
        assert result["id"] == str(mem_id)
        assert result["content"] == "User likes dark mode"
        assert result["kind"] == "preference"

    async def test_search_returns_results(self, store: MemoryStore) -> None:
        """Search returns rows ordered by similarity."""
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_row = MagicMock()
        mock_row.__getitem__ = MagicMock()
        mock_row.__getitem__.side_effect = lambda i: [
            str(uuid.uuid4()),  # id
            "00000000-0000-0000-0000-000000000001",  # tenant_id
            None,  # session_id
            "preference",  # kind
            "User likes dark mode",  # content
            {"user_id": "u1"},  # metadata_
            0.8,  # importance
            None,  # created_at
            None,  # last_accessed_at
            0.95,  # similarity
        ][i]

        mock_session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[mock_row])))

        with patch("nexus.memory.store.async_session", return_value=mock_session):
            results = await store.search(
                query_embedding=[0.1, 0.2, 0.3],
                top_k=5,
            )

        assert len(results) == 1
        assert results[0]["similarity"] == 0.95
        assert results[0]["content"] == "User likes dark mode"

    async def test_search_with_namespace(self, store: MemoryStore) -> None:
        """Search filters by namespace (tenant + kind)."""
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        with patch("nexus.memory.store.async_session", return_value=mock_session):
            results = await store.search(
                query_embedding=[0.1, 0.2],
                namespace=("tenant_1", "memories", "preference"),
                top_k=3,
            )

        assert results == []
        # Verify the SQL contained the namespace filters
        call_sql = mock_session.execute.call_args[0][0].text
        assert "tenant_id" in call_sql
        assert "kind" in call_sql

    async def test_search_with_metadata_filter(self, store: MemoryStore) -> None:
        """Search filters by metadata JSONB key."""
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        with patch("nexus.memory.store.async_session", return_value=mock_session):
            results = await store.search(
                query_embedding=[0.1],
                top_k=3,
                metadata_filter={"user_id": "u1"},
            )

        assert results == []
        call_sql = mock_session.execute.call_args[0][0].text
        assert "metadata_" in call_sql

    async def test_delete_returns_true(self, store: MemoryStore) -> None:
        mock_repo = MagicMock()
        mock_repo.delete = AsyncMock(return_value=True)

        with patch("nexus.memory.store.async_session"):
            with patch("nexus.memory.store.TenantScopedRepository", return_value=mock_repo):
                deleted = await store.delete(("tid", "memories", "fact"), uuid.uuid4())

        assert deleted is True

    async def test_delete_returns_false(self, store: MemoryStore) -> None:
        mock_repo = MagicMock()
        mock_repo.delete = AsyncMock(return_value=False)

        with patch("nexus.memory.store.async_session"):
            with patch("nexus.memory.store.TenantScopedRepository", return_value=mock_repo):
                deleted = await store.delete(("tid", "memories", "fact"), uuid.uuid4())

        assert deleted is False
