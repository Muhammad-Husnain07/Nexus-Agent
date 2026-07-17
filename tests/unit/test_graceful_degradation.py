"""Tests for graceful degradation manager — LLM/tool/DB outage handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.errors.graceful_degradation import DegradationManager


class TestDegradationManager:
    """Verify degradation detection and messages."""

    @pytest.fixture
    def manager(self) -> DegradationManager:
        return DegradationManager()

    async def test_check_llm_available_when_no_circuit_breakers(
        self, manager: DegradationManager
    ) -> None:
        with patch("nexus.errors.circuit_breaker.registry") as mock_reg:
            mock_reg.all_open.return_value = []
            assert await manager.check_llm_available() is True

    async def test_check_llm_unavailable_when_all_open(
        self, manager: DegradationManager
    ) -> None:
        with patch("nexus.errors.circuit_breaker.registry") as mock_reg:
            mock_reg.all_open.return_value = ["llm:openai", "llm:anthropic"]
            assert await manager.check_llm_available() is False

    async def test_check_llm_partially_available(
        self, manager: DegradationManager
    ) -> None:
        with patch("nexus.errors.circuit_breaker.registry") as mock_reg:
            mock_reg.all_open.return_value = ["llm:openai"]
            assert await manager.check_llm_available() is True

    async def test_check_tool_available(self, manager: DegradationManager) -> None:
        with patch("nexus.errors.circuit_breaker.registry") as mock_reg:
            mock_reg.state_of.return_value = "closed"
            assert await manager.check_tool_available("send_email") is True

    async def test_check_tool_unavailable(self, manager: DegradationManager) -> None:
        with patch("nexus.errors.circuit_breaker.registry") as mock_reg:
            mock_reg.state_of.return_value = "open"
            assert await manager.check_tool_available("send_email") is False

    async def test_degraded_llm_response_returns_string(
        self, manager: DegradationManager
    ) -> None:
        msg = await manager.degraded_llm_response()
        assert isinstance(msg, str)
        assert len(msg) > 10

    async def test_degraded_tool_response_returns_dict(
        self, manager: DegradationManager
    ) -> None:
        result = await manager.degraded_tool_response("test_tool")
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "degraded"

    async def test_check_db_available_with_mock(
        self, manager: DegradationManager
    ) -> None:
        with (
            patch("nexus.db.base.async_session") as mock_async_session,
        ):
            fake_session = AsyncMock()
            fake_session.__aenter__.return_value = fake_session
            mock_async_session.return_value = fake_session
            assert await manager.check_db_available() is True
