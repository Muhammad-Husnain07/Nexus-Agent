"""Tenant-scoped repositories for Session and Message CRUD."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexus.db.context import get_tenant
from nexus.db.models.session import Message as MessageModel
from nexus.db.models.session import Session as SessionModel
from nexus.db.repositories import TenantScopedRepository


class SessionRepository(TenantScopedRepository[SessionModel]):
    """Tenant-scoped CRUD for sessions with paginated listing."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SessionModel)

    async def create(  # type: ignore[override]
        self,
        user_id: uuid.UUID,
        title: str = "New Session",
        metadata_: dict | None = None,
    ) -> SessionModel:
        return await super().create(
            user_id=user_id,
            title=title,
            metadata_=metadata_ or {},
        )

    async def list(  # type: ignore[override]
        self,
        tenant_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SessionModel], int]:
        tid = tenant_id or get_tenant()
        stmt = select(self._model).where(self._model.tenant_id == tid)

        if user_id is not None:
            stmt = stmt.where(self._model.user_id == user_id)
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

    async def get_with_messages(self, session_id: uuid.UUID) -> SessionModel | None:
        tid = get_tenant()
        stmt = (
            select(self._model)
            .where(self._model.id == session_id)
            .where(self._model.tenant_id == tid)
            .options(selectinload(self._model.messages))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def archive(self, session_id: uuid.UUID) -> SessionModel | None:
        tid = get_tenant()
        stmt = (
            update(self._model)
            .where(self._model.id == session_id)
            .where(self._model.tenant_id == tid)
            .values(status="archived")
            .returning(self._model)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one_or_none()

    async def get_message_count(self, session_id: uuid.UUID) -> int:
        tid = get_tenant()
        stmt = (
            select(func.count(MessageModel.id))
            .where(MessageModel.session_id == session_id)
            .where(MessageModel.tenant_id == tid)
        )
        result = await self._session.execute(stmt)
        return result.scalar() or 0


class MessageRepository(TenantScopedRepository[MessageModel]):
    """Tenant-scoped CRUD for messages with paginated listing."""

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
        tid = get_tenant()
        stmt = (
            select(self._model)
            .where(self._model.session_id == session_id)
            .where(self._model.tenant_id == tid)
        )

        if before_id is not None:
            sub = (
                select(self._model.created_at)
                .where(self._model.id == before_id)
                .where(self._model.tenant_id == tid)
            )
            before_ts_result = await self._session.execute(sub)
            before_ts = before_ts_result.scalar_one_or_none()
            if before_ts is not None:
                stmt = stmt.where(self._model.created_at < before_ts)

        if after_id is not None:
            sub = (
                select(self._model.created_at)
                .where(self._model.id == after_id)
                .where(self._model.tenant_id == tid)
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

    async def get_by_session(self, session_id: uuid.UUID) -> Sequence[MessageModel]:
        tid = get_tenant()
        stmt = (
            select(self._model)
            .where(self._model.session_id == session_id)
            .where(self._model.tenant_id == tid)
            .order_by(self._model.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def get_last_n(self, session_id: uuid.UUID, n: int = 20) -> list[MessageModel]:
        tid = get_tenant()
        stmt = (
            select(self._model)
            .where(self._model.session_id == session_id)
            .where(self._model.tenant_id == tid)
            .order_by(self._model.created_at.desc())
            .limit(n)
        )
        result = await self._session.execute(stmt)
        return list(reversed(result.scalars().all()))

    async def create_many(self, messages: list[dict]) -> list[MessageModel]:
        tid = get_tenant()
        instances: list[MessageModel] = []
        for msg in messages:
            instance = MessageModel(
                tenant_id=tid,
                session_id=msg["session_id"],
                role=msg["role"],
                content=msg.get("content", {}),
                tool_calls=msg.get("tool_calls"),
                parent_message_id=msg.get("parent_message_id"),
            )
            self._session.add(instance)
            instances.append(instance)
        await self._session.flush()
        return instances
