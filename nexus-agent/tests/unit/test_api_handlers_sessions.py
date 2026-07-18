"""Direct handler tests for sessions/api.py — call route functions inline."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from nexus.sessions.api import (
    add_message,
    archive_session,
    create_session,
    get_messages,
    get_session,
    list_sessions,
    rename_session,
    update_session,
)
from nexus.sessions.schemas import (
    MessageCreate,
    SessionCreate,
    SessionRead,
    SessionUpdate,
)


@pytest.fixture
def mock_service() -> MagicMock:
    svc = MagicMock()
    svc.create_session = AsyncMock()
    svc.get_session = AsyncMock()
    svc.list_sessions = AsyncMock()
    svc.update_session = AsyncMock()
    svc.archive_session = AsyncMock()
    svc.rename_session = AsyncMock()
    svc.get_messages = AsyncMock()
    svc.add_message = AsyncMock()
    return svc


@pytest.fixture
def session_read() -> SessionRead:
    return SessionRead(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), user_id=uuid.uuid4(),
        title="Test", status="active",
        created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
        metadata_={},
    )


class TestSessionsAPI:
    async def test_create(self, mock_service: MagicMock, session_read: SessionRead) -> None:
        mock_service.create_session.return_value = session_read
        result = await create_session(SessionCreate(title="Test"), mock_service, uuid.uuid4(), uuid.uuid4())
        assert result.title == "Test"

    async def test_get_found(self, mock_service: MagicMock, session_read: SessionRead) -> None:
        mock_service.get_session.return_value = session_read
        result = await get_session(session_read.id, mock_service)
        assert result.id == session_read.id

    async def test_get_not_found(self, mock_service: MagicMock) -> None:
        mock_service.get_session.return_value = None
        with pytest.raises(HTTPException, match="Session not found"):
            await get_session(uuid.uuid4(), mock_service)

    async def test_list(self, mock_service: MagicMock) -> None:
        from nexus.sessions.schemas import SessionList
        mock_service.list_sessions.return_value = SessionList(items=[], total=0, page=1, page_size=20)
        result = await list_sessions(mock_service, uuid.uuid4())
        assert result.total == 0

    async def test_update_not_found(self, mock_service: MagicMock) -> None:
        mock_service.update_session.return_value = None
        with pytest.raises(HTTPException, match="Session not found"):
            await update_session(uuid.uuid4(), SessionUpdate(), mock_service)

    async def test_archive_not_found(self, mock_service: MagicMock) -> None:
        mock_service.archive_session.return_value = None
        with pytest.raises(HTTPException, match="Session not found"):
            await archive_session(uuid.uuid4(), mock_service)

    async def test_rename_not_found(self, mock_service: MagicMock) -> None:
        mock_service.rename_session.return_value = None
        with pytest.raises(HTTPException, match="Session not found"):
            await rename_session(uuid.uuid4(), mock_service)

    async def test_get_messages(self, mock_service: MagicMock) -> None:
        from nexus.sessions.schemas import MessageList
        mock_service.get_messages.return_value = MessageList(items=[], total=0, page=1, page_size=50)
        result = await get_messages(uuid.uuid4(), mock_service)
        assert result.total == 0
