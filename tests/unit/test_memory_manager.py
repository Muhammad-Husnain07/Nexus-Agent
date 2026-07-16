"""Unit tests for MemoryManager — extract, retrieve, dedup."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.llm.client import LLMResponse, UsageInfo
from nexus.memory.manager import MemoryManager


class TestMemoryManager:
    """MemoryManager — extract_and_store, retrieve_relevant, decay."""

    @pytest.fixture
    def mock_store(self) -> MagicMock:
        store = MagicMock()
        store.put = AsyncMock(return_value="mem_id")
        store.search = AsyncMock(return_value=[])
        store.delete = AsyncMock(return_value=True)
        return store

    @pytest.fixture
    def mock_llm(self) -> MagicMock:
        llm = MagicMock()
        llm.complete = AsyncMock(
            side_effect=[
                # First call: extraction
                LLMResponse(
                    content=json.dumps([
                        {"kind": "preference", "content": "User likes dark mode", "importance": 0.8},
                    ]),
                    usage=UsageInfo(prompt_tokens=10, completion_tokens=10, total_tokens=20),
                    model="gpt-4o",
                    provider="openai",
                    latency_ms=50,
                    cost_usd=0.001,
                ),
                # Second call: summarization
                LLMResponse(
                    content="User asked about dark mode. Preference stored.",
                    usage=UsageInfo(prompt_tokens=40, completion_tokens=15, total_tokens=55),
                    model="gpt-4o",
                    provider="openai",
                    latency_ms=60,
                    cost_usd=0.001,
                ),
            ],
        )
        return llm

    @pytest.fixture
    def manager(self, mock_store: MagicMock, mock_llm: MagicMock) -> MemoryManager:
        mgr = MemoryManager(store=mock_store, llm=mock_llm)
        mgr._memory_settings.enabled = True
        mgr._memory_settings.similarity_threshold = 0.92
        return mgr

    async def _patch_embedding(self, manager: MemoryManager) -> None:
        """Patch embedding generation to return a vector."""
        manager._generate_embedding = AsyncMock(return_value=[0.1] * 10)

    async def test_extract_and_store_disabled(self, mock_store: MagicMock, mock_llm: MagicMock) -> None:
        mgr = MemoryManager(store=mock_store, llm=mock_llm)
        mgr._memory_settings.enabled = False

        result = await mgr.extract_and_store(
            tenant_id="t1", user_id="u1", session_id="s1", agent_state={}
        )
        assert result == []

    async def test_extract_and_store_returns_ids(
        self, manager: MemoryManager, mock_store: MagicMock
    ) -> None:
        await self._patch_embedding(manager)
        result = await manager.extract_and_store(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            agent_state={
                "messages": [{"role": "user", "content": "hello"}],
                "tool_results": [{"tool_name": "test", "status": "success"}],
                "plan": [],
                "errors": [],
                "intent": {},
            },
        )
        assert len(result) >= 1
        assert mock_store.put.called

    async def test_retrieve_relevant_returns_list(
        self, manager: MemoryManager, mock_store: MagicMock
    ) -> None:
        await self._patch_embedding(manager)
        mock_store.search.return_value = [
            {"id": "1", "content": "test", "kind": "preference", "similarity": 0.95, "importance": 0.8},
        ]

        results = await manager.retrieve_relevant(
            tenant_id="t1", user_id="u1", query="dark mode"
        )
        assert len(results) == 1
        assert results[0]["similarity"] == 0.95

    async def test_retrieve_formatted(self, manager: MemoryManager, mock_store: MagicMock) -> None:
        await self._patch_embedding(manager)
        mock_store.search.return_value = [
            {"id": "1", "content": "User likes dark mode", "kind": "preference",
             "similarity": 0.95, "importance": 0.8},
        ]

        formatted = await manager.retrieve_formatted(
            tenant_id="t1", user_id="u1", query="theme"
        )
        assert "dark mode" in formatted
        assert "preference" in formatted

    async def test_dedup_updates_existing(
        self, manager: MemoryManager, mock_store: MagicMock
    ) -> None:
        """When a similar memory exists (similarity > 0.92), update instead of insert."""
        await self._patch_embedding(manager)
        existing_uuid = str(uuid.uuid4())
        mock_store.search.return_value = [
            {"id": existing_uuid, "content": "Old content", "kind": "preference",
             "similarity": 0.95, "importance": 0.7},
        ]

        await manager.extract_and_store(
            tenant_id="t1",
            user_id="u1",
            session_id="s1",
            agent_state={
                "messages": [{"role": "user", "content": "I like dark mode"}],
                "tool_results": [],
                "plan": [],
                "errors": [],
                "intent": {},
            },
        )
        assert mock_store.put.called

    async def test_decay(self, manager: MemoryManager) -> None:
        with patch("nexus.memory.manager.async_session") as mock_async_session:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session.execute = AsyncMock()
            mock_session.execute.return_value.all = MagicMock(return_value=[])
            mock_session.commit = AsyncMock()
            mock_async_session.return_value = mock_session

            archived = await manager.decay(days_threshold=90)
            assert archived == 0
