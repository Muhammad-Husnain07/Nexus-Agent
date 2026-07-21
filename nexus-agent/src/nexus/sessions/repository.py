"""Repositories for Session and Message CRUD."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexus.db.models.session import Message as MessageModel
from nexus.db.models.session import Session as SessionModel
from nexus.db.repositories.base import GenericRepository


class SessionRepository(GenericRepository[SessionModel]):
    """CRUD for sessions with paginated listing."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SessionModel)

    async def create(  # type: ignore[override]
        self,
        title: str = "New Session",
        metadata_: dict | None = None,
        **kwargs: Any,
    ) -> SessionModel:
        return await super().create(
            title=title,
            metadata_=metadata_ or {},
            **kwargs,
        )

    async def list(  # type: ignore[override]
        self,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SessionModel], int]:
        stmt = select(self._model)

        if status is not None:
            stmt = stmt.where(self._model.status == status)

        count_stmt = stmt.with_only_columns(func.count(self._model.id)).order_by(None)
        total_result = await self._session.execute(count_stmt)
        total: int = total_result.scalar() or 0

        stmt = (
            stmt.order_by(self._model.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_with_messages(self, id: uuid.UUID) -> SessionModel | None:
        """Get a session eagerly loaded with its messages."""
        stmt = (
            select(self._model)
            .where(self._model.id == id)
            .options(selectinload(self._model.messages))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_message_count(self, id: uuid.UUID) -> int:
        """Return the count of messages in a session."""
        from sqlalchemy import select as sa_select

        stmt = sa_select(func.count()).select_from(MessageModel).where(
            MessageModel.session_id == id
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def archive(self, id: uuid.UUID) -> SessionModel | None:
        """Set session status to archived."""
        return await self.update(id, status="archived")

    async def count_active(self) -> int:
        """Count active sessions."""
        stmt = select(func.count(self._model.id)).where(self._model.status == "active")
        result = await self._session.execute(stmt)
        return result.scalar() or 0



class MessageRepository(GenericRepository[MessageModel]):
    """CRUD for messages with paginated listing."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MessageModel)

    async def create(  # type: ignore[override]
        self,
        session_id: uuid.UUID,
        role: str,
        content: dict | None = None,
        tool_calls: list[dict] | None = None,
        parent_id: uuid.UUID | None = None,
    ) -> MessageModel:
        return await super().create(
            session_id=session_id,
            role=role,
            content=content or {},
            tool_calls=tool_calls,
            parent_message_id=parent_id,
        )

    async def list_by_session(  # type: ignore[override]
        self,
        session_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        before_id: uuid.UUID | None = None,
        after_id: uuid.UUID | None = None,
    ) -> tuple[list[MessageModel], int]:
        stmt = (
            select(self._model)
            .where(self._model.session_id == session_id)
        )

        if before_id is not None:
            sub = (
                select(self._model.created_at)
                .where(self._model.id == before_id)
            )
            before_ts_result = await self._session.execute(sub)
            before_ts = before_ts_result.scalar_one_or_none()
            if before_ts is not None:
                stmt = stmt.where(self._model.created_at < before_ts)

        if after_id is not None:
            sub = (
                select(self._model.created_at)
                .where(self._model.id == after_id)
            )
            after_ts_result = await self._session.execute(sub)
            after_ts = after_ts_result.scalar_one_or_none()
            if after_ts is not None:
                stmt = stmt.where(self._model.created_at > after_ts)

        count_stmt = stmt.with_only_columns(func.count(self._model.id)).order_by(None)
        total_result = await self._session.execute(count_stmt)
        total: int = total_result.scalar() or 0

        stmt = (
            stmt.order_by(self._model.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_last_n(self, session_id: uuid.UUID, n: int = 2) -> list[MessageModel]:
        """Get the last N messages for a session (ordered by created_at DESC)."""
        stmt = (
            select(self._model)
            .where(self._model.session_id == session_id)
            .order_by(self._model.created_at.desc())
            .limit(n)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def search_by_content(self, query: str, limit: int = 20) -> list[MessageModel]:
        """Search messages by content (simple ILIKE)."""
        stmt = (
            select(self._model)
            .where(self._model.content["text"].as_string().ilike(f"%{query}%"))
            .order_by(self._model.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_session_messages_for_export(self, session_id: uuid.UUID) -> Sequence[MessageModel]:
        """Get all messages for a session in ascending order."""
        stmt = (
            select(self._model)
            .where(self._model.session_id == session_id)
            .order_by(self._model.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def delete_by_session(self, session_id: uuid.UUID) -> int:
        """Delete all messages for a session."""
        stmt = select(self._model).where(self._model.session_id == session_id)
        result = await self._session.execute(stmt)
        messages = result.scalars().all()
        for msg in messages:
            await self._session.delete(msg)
        return len(messages)

    async def create_many(self, messages: list[dict]) -> list[MessageModel]:
        """Bulk-create messages from a list of dicts."""
        instances = [MessageModel(**m) for m in messages]
        for inst in instances:
            self._session.add(inst)
        await self._session.flush()
        return instances

    async def update_message_feedback(self, message_id: uuid.UUID, feedback: dict[str, Any]) -> MessageModel | None:
        """Update feedback on a message."""
        result = await self._session.execute(
            update(MessageModel)
            .where(MessageModel.id == message_id)
            .values(feedback=feedback)
            .returning(MessageModel)
        )
        return result.scalar_one_or_none()
