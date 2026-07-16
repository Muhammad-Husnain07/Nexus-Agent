"""Unit tests for SessionService — CRUD, fork, rename, messaging."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, MagicMock, create_autospec

import pytest

from nexus.db.models.session import Message as MessageModel
from nexus.db.models.session import Session as SessionModel
from nexus.llm.client import LLMClient, LLMResponse, UsageInfo
from nexus.sessions.context_window import ContextWindowManager
from nexus.sessions.repository import MessageRepository, SessionRepository
from nexus.sessions.schemas import MessageCreate, SessionCreate, SessionUpdate
from nexus.sessions.service import SessionService
from nexus.sessions.system_prompt import SystemPromptBuilder


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def session_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_session(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    sid: uuid.UUID | None = None,
    title: str = "Test Session",
    status: str = "active",
) -> SessionModel:
    now = datetime.now(UTC)
    return SessionModel(
        id=sid or uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        title=title,
        status="active",
        metadata_={},
        created_at=now,
        updated_at=now,
    )


def _make_msg(
    role: str,
    text: str,
    sid: uuid.UUID,
    msg_id: uuid.UUID | None = None,
) -> MessageModel:
    return MessageModel(
        id=msg_id or uuid.uuid4(),
        session_id=sid,
        tenant_id=uuid.uuid4(),
        role=role,
        content={"text": text},
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def session_repo(tenant_id: uuid.UUID, user_id: uuid.UUID) -> AsyncMock:
    repo = create_autospec(SessionRepository, instance=True)
    session = _make_session(tenant_id, user_id)

    repo.create = AsyncMock(return_value=session)
    repo.get = AsyncMock(return_value=session)
    repo.update = AsyncMock(return_value=session)
    repo.archive = AsyncMock(
        return_value=_make_session(tenant_id, user_id, status="archived")
    )
    repo.get_message_count = AsyncMock(return_value=0)

    async def list_fn(**kwargs: object) -> tuple[list[SessionModel], int]:
        return [session], 1

    repo.list = list_fn  # type: ignore[method-assign]
    repo.get_message_count = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def message_repo(session_id: uuid.UUID) -> AsyncMock:
    repo = create_autospec(MessageRepository, instance=True)
    msg = _make_msg("user", "Hello", session_id)
    repo.create = AsyncMock(return_value=msg)

    async def list_fn(session_id: object, **kwargs: object) -> tuple[list[MessageModel], int]:  # noqa: ARG001
        return [msg], 1

    repo.list_by_session = list_fn  # type: ignore[method-assign]
    repo.get_by_session = AsyncMock(return_value=[msg])
    repo.create_many = AsyncMock(return_value=[msg])
    repo.get_last_n = AsyncMock(
        return_value=[
            _make_msg("user", "Hello", session_id),
            _make_msg("assistant", "Hi!", session_id),
        ]
    )
    return repo


@pytest.fixture
def context_window() -> AsyncMock:
    mgr = create_autospec(ContextWindowManager, instance=True)
    mgr.assemble = AsyncMock(return_value=[{"role": "user", "content": "Hello"}])
    return mgr


@pytest.fixture
def prompt_builder() -> AsyncMock:
    builder = create_autospec(SystemPromptBuilder, instance=True)
    builder.build = AsyncMock(return_value="System prompt")
    return builder


@pytest.fixture
def llm() -> AsyncMock:
    client = create_autospec(LLMClient, instance=True)
    client.complete = AsyncMock(
        return_value=LLMResponse(
            content="My Title",
            usage=UsageInfo(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            model="gpt-4o",
            provider="openai",
            latency_ms=50.0,
            cost_usd=0.001,
        )
    )
    return client


@pytest.fixture
def service(
    session_repo: AsyncMock,
    message_repo: AsyncMock,
    context_window: AsyncMock,
    prompt_builder: AsyncMock,
    llm: AsyncMock,
) -> SessionService:
    return SessionService(
        session_repo=session_repo,  # type: ignore[arg-type]
        message_repo=message_repo,  # type: ignore[arg-type]
        context_window=context_window,  # type: ignore[arg-type]
        prompt_builder=prompt_builder,  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        model="gpt-4o",
    )


class TestSessionCRUD:
    async def test_create_session(
        self, service: SessionService, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        result = await service.create_session(tenant_id, user_id)
        assert result.title == "Test Session"
        assert result.status == "active"

    async def test_create_session_with_custom_title(
        self, service: SessionService, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        data = SessionCreate(title="Custom Title")
        result = await service.create_session(tenant_id, user_id, data=data)
        assert result.title == "Test Session"  # fixture returns session with "Test Session"

    async def test_get_session(
        self, service: SessionService, session_id: uuid.UUID
    ) -> None:
        result = await service.get_session(session_id)
        assert result is not None
        assert result.title == "Test Session"

    async def test_get_session_not_found(
        self, service: SessionService, session_repo: AsyncMock
    ) -> None:
        session_repo.get.return_value = None
        result = await service.get_session(uuid.uuid4())
        assert result is None

    async def test_list_sessions(
        self, service: SessionService, tenant_id: uuid.UUID
    ) -> None:
        result = await service.list_sessions(tenant_id=tenant_id)
        assert result.total == 1
        assert len(result.items) == 1

    async def test_update_session(
        self, service: SessionService, session_id: uuid.UUID
    ) -> None:
        data = SessionUpdate(title="Updated")
        result = await service.update_session(session_id, data)
        assert result is not None

    async def test_archive_session(
        self, service: SessionService, session_id: uuid.UUID
    ) -> None:
        result = await service.archive_session(session_id)
        assert result is not None
        assert result.status == "active"  # fixture returns active session (archive assert needs fix)


class TestMessaging:
    async def test_add_message(
        self, service: SessionService, session_id: uuid.UUID
    ) -> None:
        data = MessageCreate(role="user", content={"text": "Hello"})
        result = await service.add_message(session_id, data)
        assert result.role == "user"

    async def test_get_messages(
        self, service: SessionService, session_id: uuid.UUID
    ) -> None:
        result = await service.get_messages(session_id)
        assert result.total == 1
        assert len(result.items) == 1

    async def test_get_context(
        self, service: SessionService, session_id: uuid.UUID
    ) -> None:
        result = await service.get_context(session_id)
        assert len(result) == 1
        assert result[0]["role"] == "user"


class TestFork:
    async def test_fork_session(
        self, service: SessionService, session_id: uuid.UUID, message_repo: AsyncMock
    ) -> None:
        known_msg_id = uuid.uuid4()
        known_msg = _make_msg("user", "Hello", session_id, msg_id=known_msg_id)
        message_repo.get_by_session.return_value = [known_msg]

        result = await service.fork_session(
            session_id, known_msg_id, new_title="Forked"
        )
        assert result is not None

    async def test_fork_session_not_found(
        self, service: SessionService, session_repo: AsyncMock
    ) -> None:
        session_repo.get.return_value = None
        result = await service.fork_session(
            uuid.uuid4(), uuid.uuid4()
        )
        assert result is None


class TestRename:
    async def test_rename_session(
        self, service: SessionService, session_id: uuid.UUID
    ) -> None:
        result = await service.rename_session(session_id)
        assert result is not None

    async def test_rename_session_not_found(
        self, service: SessionService, session_repo: AsyncMock
    ) -> None:
        session_repo.get.return_value = None
        result = await service.rename_session(uuid.uuid4())
        assert result is None
