"""Integration tests for the sessions API — CRUD, fork, rename, summarization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from nexus.db.models.session import Message as MessageModel
from nexus.db.models.session import Session as SessionModel
from nexus.sessions.schemas import SessionRead
from nexus.sessions.service import SessionService

pytestmark = [pytest.mark.integration]


def _make_session(
    sid: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    title: str = "Test Session",
    status: str = "active",
) -> SessionModel:
    now = datetime.now(UTC)
    return SessionModel(
        id=sid or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        title=title,
        status=status,
        metadata_={},
        created_at=now,
        updated_at=now,
    )


def _make_msg(
    role: str,
    text: str,
    sid: uuid.UUID,
    msg_id: uuid.UUID | None = None,
    tool_calls: list[dict] | None = None,
) -> MessageModel:
    return MessageModel(
        id=msg_id or uuid.uuid4(),
        session_id=sid,
        tenant_id=uuid.uuid4(),
        role=role,
        content={"text": text},
        tool_calls=tool_calls,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_session_service() -> MagicMock:
    service = MagicMock(spec=SessionService)
    service.create_session = AsyncMock()
    service.get_session = AsyncMock()
    service.list_sessions = AsyncMock()
    service.update_session = AsyncMock()
    service.archive_session = AsyncMock()
    service.fork_session = AsyncMock()
    service.rename_session = AsyncMock()
    service.add_message = AsyncMock()
    service.get_messages = AsyncMock()
    service.get_context = AsyncMock()
    return service


@pytest.fixture
def app(mock_session_service: MagicMock) -> FastAPI:
    a = FastAPI()

    from nexus.sessions.api import router as sessions_router

    a.include_router(sessions_router)

    async def mock_service() -> MagicMock:
        return mock_session_service

    from nexus.sessions import api as sessions_api_module

    a.dependency_overrides[sessions_api_module.get_session_service] = mock_service

    # Override auth dependencies so tests don't need real credentials
    import uuid

    from nexus.api.depends import _current_tenant
    from nexus.security.rbac import get_current_user, Role

    async def mock_tenant() -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-000000000001")

    async def mock_user_with_role() -> tuple[uuid.UUID, Role]:
        return uuid.UUID("00000000-0000-0000-0000-000000000002"), Role.TENANT_ADMIN

    a.dependency_overrides[_current_tenant] = mock_tenant
    a.dependency_overrides[get_current_user] = mock_user_with_role
    return a


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _session_read(**overrides: object) -> SessionRead:
    now = datetime.now(UTC)
    defaults: dict = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "title": "Test Session",
        "status": "active",
        "metadata": {},
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    }
    defaults.update(overrides)
    return SessionRead(**defaults)


class TestSessionsAPI:
    async def test_create_session(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        expected = _session_read(title="New Chat")
        mock_session_service.create_session.return_value = expected

        resp = await client.post("/api/v1/sessions", json={"title": "New Chat"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "New Chat"

    async def test_list_sessions(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        from nexus.sessions.schemas import SessionList

        expected = SessionList(
            items=[_session_read()],
            total=1,
            page=1,
            page_size=20,
        )
        mock_session_service.list_sessions.return_value = expected

        resp = await client.get("/api/v1/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    async def test_get_session(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        expected = _session_read()
        mock_session_service.get_session.return_value = expected

        resp = await client.get(f"/api/v1/sessions/{expected.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(expected.id)

    async def test_get_session_not_found(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        mock_session_service.get_session.return_value = None

        resp = await client.get(f"/api/v1/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_update_session(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        expected = _session_read(title="Updated")
        mock_session_service.update_session.return_value = expected

        resp = await client.patch(
            f"/api/v1/sessions/{expected.id}",
            json={"title": "Updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    async def test_archive_session(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        sid = uuid.uuid4()
        expected = _session_read(id=sid, status="archived")
        mock_session_service.archive_session.return_value = expected

        resp = await client.delete(f"/api/v1/sessions/{sid}")
        assert resp.status_code == 204

    async def test_archive_session_not_found(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        mock_session_service.archive_session.return_value = None
        resp = await client.delete(f"/api/v1/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_fork_session(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        sid = uuid.uuid4()
        expected = _session_read(title="Forked Session")
        mock_session_service.fork_session.return_value = expected

        resp = await client.post(
            f"/api/v1/sessions/{sid}/fork",
            json={"message_id": str(uuid.uuid4()), "new_title": "Forked Session"},
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Forked Session"

    async def test_fork_session_not_found(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        mock_session_service.fork_session.return_value = None
        resp = await client.post(
            f"/api/v1/sessions/{uuid.uuid4()}/fork",
            json={"message_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    async def test_rename_session(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        sid = uuid.uuid4()
        expected = _session_read(id=sid, title="New Title")
        mock_session_service.rename_session.return_value = expected

        resp = await client.post(f"/api/v1/sessions/{sid}/rename")
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    async def test_add_message(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        from nexus.sessions.schemas import MessageRead

        sid = uuid.uuid4()
        mid = uuid.uuid4()
        now = datetime.now(UTC)
        expected = MessageRead(
            id=mid,
            session_id=sid,
            role="user",
            content={"text": "Hello"},
            tool_calls=None,
            parent_message_id=None,
            created_at=now,
        )
        mock_session_service.add_message.return_value = expected

        resp = await client.post(
            f"/api/v1/sessions/{sid}/messages",
            json={"role": "user", "content": {"text": "Hello"}},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "user"

    async def test_get_messages(
        self, client: AsyncClient, mock_session_service: MagicMock
    ) -> None:
        from nexus.sessions.schemas import MessageList, MessageRead

        sid = uuid.uuid4()
        now = datetime.now(UTC)
        msg = MessageRead(
            id=uuid.uuid4(),
            session_id=sid,
            role="user",
            content={"text": "Hello"},
            tool_calls=None,
            parent_message_id=None,
            created_at=now,
        )
        mock_session_service.get_messages.return_value = MessageList(
            items=[msg], total=1, page=1, page_size=50
        )

        resp = await client.get(f"/api/v1/sessions/{sid}/messages")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
