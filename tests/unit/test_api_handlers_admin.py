"""Direct handler tests for admin.py — call route functions inline."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


class TestAdminHandlers:
    """Test admin handler functions with mocked dependencies."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        s = AsyncMock()
        s.flush = AsyncMock()
        s.commit = AsyncMock()
        return s

    @pytest.fixture
    def tid(self) -> uuid.UUID:
        return uuid.uuid4()

    async def test_list_tenants_empty(self, mock_session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        from nexus.api.admin import list_tenants
        result = await list_tenants(mock_session, status=None, page=1, page_size=20)
        assert result == []

    async def test_get_tenant_detail_not_found(self, mock_session: AsyncMock) -> None:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        with patch("nexus.api.admin.GenericRepository", return_value=repo):
            from nexus.api.admin import get_tenant_detail
            with pytest.raises(HTTPException, match="Tenant not found"):
                await get_tenant_detail(uuid.uuid4(), mock_session)

    async def test_list_audit_log_empty(self, mock_session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        from nexus.api.admin import list_audit_log
        result = await list_audit_log(mock_session, tenant_id=None, action=None, page=1, page_size=50)
        assert result == []

    async def test_list_users_empty(self, mock_session: AsyncMock, tid: uuid.UUID) -> None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        from nexus.api.admin import list_users
        result = await list_users(tid, mock_session, role=None, page=1, page_size=20)
        assert result == []
