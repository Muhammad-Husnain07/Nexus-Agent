"""SessionService — session lifecycle, messaging, forking, and renaming."""

from __future__ import annotations

import uuid

import structlog

from nexus.config.settings import get_settings
from nexus.db.models.session import Message as MessageModel
from nexus.db.models.session import Session as SessionModel
from nexus.llm.client import LLMClient
from nexus.sessions.context_window import ContextWindowManager
from nexus.sessions.repository import MessageRepository, SessionRepository
from nexus.sessions.schemas import (
    MessageCreate,
    MessageList,
    MessageRead,
    SessionCreate,
    SessionList,
    SessionRead,
    SessionUpdate,
)
from nexus.sessions.system_prompt import SystemPromptBuilder

logger = structlog.get_logger("nexus.sessions.service")

_RENAME_PROMPT = (
    "Suggest a concise title (max 8 words) for a conversation "
    "that starts with the following exchange. Respond with only the title, "
    "no explanation or quotes."
)


def _session_to_read(session: SessionModel, message_count: int = 0) -> SessionRead:
    return SessionRead(
        id=session.id,
        tenant_id=session.tenant_id,
        user_id=session.user_id,
        title=session.title,
        status=session.status,
        metadata=session.metadata_ or {},
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=message_count,
    )


def _message_to_read(msg: MessageModel) -> MessageRead:
    return MessageRead(
        id=msg.id,
        session_id=msg.session_id,
        role=msg.role,
        content=msg.content or {},
        tool_calls=msg.tool_calls,
        parent_message_id=msg.parent_message_id,
        created_at=msg.created_at,
    )


class SessionService:
    """Orchestrates session lifecycle, messaging, forking, and renaming.

    Wraps ``SessionRepository`` and ``MessageRepository`` with business
    logic for context window management and LLM-powered features.
    """

    def __init__(
        self,
        session_repo: SessionRepository,
        message_repo: MessageRepository,
        context_window: ContextWindowManager,
        prompt_builder: SystemPromptBuilder | None = None,
        llm_client: LLMClient | None = None,
        model: str | None = None,
    ) -> None:
        self._session_repo = session_repo
        self._message_repo = message_repo
        self._context_window = context_window
        self._prompt_builder = prompt_builder or SystemPromptBuilder(llm_client=llm_client)
        self._llm = llm_client or LLMClient()
        self._model = model or get_settings().llm.default_model

    async def create_session(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: SessionCreate | None = None,
    ) -> SessionRead:
        title = data.title if data and data.title else "New Session"
        metadata_ = data.metadata_ if data else None
        session = await self._session_repo.create(
            user_id=user_id,
            title=title,
            metadata_=metadata_,
        )
        logger.info("session_created", session_id=str(session.id), user_id=str(user_id))
        return _session_to_read(session)

    async def get_session(self, session_id: uuid.UUID) -> SessionRead | None:
        session = await self._session_repo.get(session_id)
        if session is None:
            return None
        count = await self._session_repo.get_message_count(session_id)
        return _session_to_read(session, count)

    async def list_sessions(
        self,
        tenant_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SessionList:
        items, total = await self._session_repo.list(
            tenant_id=tenant_id,
            user_id=user_id,
            status=status,
            page=page,
            page_size=page_size,
        )
        reads = [_session_to_read(s) for s in items]
        return SessionList(items=reads, total=total, page=page, page_size=page_size)

    async def update_session(
        self, session_id: uuid.UUID, data: SessionUpdate
    ) -> SessionRead | None:
        kwargs: dict = {}
        if data.title is not None:
            kwargs["title"] = data.title
        if data.status is not None:
            kwargs["status"] = data.status
        if data.metadata_ is not None:
            kwargs["metadata_"] = data.metadata_

        session = await self._session_repo.update(session_id, **kwargs)
        if session is None:
            return None
        count = await self._session_repo.get_message_count(session_id)
        return _session_to_read(session, count)

    async def archive_session(self, session_id: uuid.UUID) -> SessionRead | None:
        session = await self._session_repo.archive(session_id)
        if session is None:
            return None
        return _session_to_read(session)

    async def fork_session(
        self,
        session_id: uuid.UUID,
        message_id: uuid.UUID,
        new_title: str | None = None,
    ) -> SessionRead | None:
        source = await self._session_repo.get(session_id)
        if source is None:
            return None

        messages = await self._message_repo.get_by_session(session_id)

        cutoff_idx: int | None = None
        for i, msg in enumerate(messages):
            if msg.id == message_id:
                cutoff_idx = i
                break

        if cutoff_idx is None:
            raise ValueError(f"Message {message_id} not found in session {session_id}")

        history_messages = list(messages[: cutoff_idx + 1])

        new_session = await self._session_repo.create(
            user_id=source.user_id,
            title=new_title or f"Fork of {source.title}",
        )

        id_map: dict[uuid.UUID, uuid.UUID | None] = {}
        bulk_data: list[dict] = []
        for msg in history_messages:
            new_parent_id = id_map.get(msg.parent_message_id) if msg.parent_message_id else None
            bulk_data.append(
                {
                    "session_id": new_session.id,
                    "role": msg.role,
                    "content": msg.content,
                    "tool_calls": msg.tool_calls,
                    "parent_message_id": new_parent_id,
                }
            )
            id_map[msg.id] = new_session.id

        await self._message_repo.create_many(bulk_data)

        logger.info(
            "session_forked",
            source_id=str(session_id),
            new_id=str(new_session.id),
            message_count=len(history_messages),
        )
        return _session_to_read(new_session, len(history_messages))

    async def rename_session(self, session_id: uuid.UUID) -> SessionRead | None:
        session = await self._session_repo.get(session_id)
        if session is None:
            return None

        messages = await self._message_repo.get_last_n(session_id, 2)
        if len(messages) < 2:
            return _session_to_read(session)

        user_msg = messages[0] if messages[0].role == "user" else messages[1]
        assistant_msg = messages[1] if messages[1].role == "assistant" else messages[0]

        user_text = (user_msg.content or {}).get("text", "")
        assistant_text = (assistant_msg.content or {}).get("text", "")

        rename_messages = [
            {"role": "system", "content": _RENAME_PROMPT},
            {
                "role": "user",
                "content": f"USER: {user_text}\nASSISTANT: {assistant_text}",
            },
        ]

        response = await self._llm.complete(
            model=self._model,
            messages=rename_messages,
            temperature=0.5,
            max_tokens=30,
        )
        new_title = (response.content or session.title).strip().strip('"')

        session = await self._session_repo.update(session_id, title=new_title)
        if session is None:
            return None

        logger.info("session_renamed", session_id=str(session_id), title=new_title)
        return _session_to_read(session)

    async def add_message(
        self,
        session_id: uuid.UUID,
        data: MessageCreate,
    ) -> MessageRead:
        msg = await self._message_repo.create(
            session_id=session_id,
            role=data.role,
            content=data.content,
            tool_calls=data.tool_calls,
            parent_id=data.parent_id,
        )
        return _message_to_read(msg)

    async def get_messages(
        self,
        session_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        before_id: uuid.UUID | None = None,
        after_id: uuid.UUID | None = None,
    ) -> MessageList:
        items, total = await self._message_repo.list_by_session(
            session_id,
            page=page,
            page_size=page_size,
            before_id=before_id,
            after_id=after_id,
        )
        reads = [_message_to_read(m) for m in items]
        return MessageList(items=reads, total=total, page=page, page_size=page_size)

    async def get_context(
        self,
        session_id: uuid.UUID,
        plan: list[dict] | None = None,
    ) -> list[dict]:
        """Assemble messages for LLM input with context window management."""
        messages = await self._message_repo.get_by_session(session_id)
        return await self._context_window.assemble(messages, plan=plan)
