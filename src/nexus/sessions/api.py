"""FastAPI router for /api/v1/sessions — CRUD, fork, rename, messages."""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.depends import TenantDep, UserDep
from nexus.db.base import get_session
from nexus.security.rbac import Permission, require_permission
from nexus.sessions.schemas import (
    ForkRequest,
    MessageCreate,
    MessageList,
    MessageRead,
    SessionCreate,
    SessionList,
    SessionRead,
    SessionUpdate,
)
from nexus.sessions.service import SessionService

logger = structlog.get_logger("nexus.sessions.api")

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_session_service(db: SessionDep) -> SessionService:
    """Dependency: create a SessionService wired to the DB session."""
    from nexus.config.settings import get_settings  # noqa: PLC0415
    from nexus.llm.client import LLMClient  # noqa: PLC0415
    from nexus.sessions.context_window import ContextWindowManager  # noqa: PLC0415
    from nexus.sessions.repository import MessageRepository, SessionRepository  # noqa: PLC0415
    from nexus.sessions.system_prompt import SystemPromptBuilder  # noqa: PLC0415

    settings = get_settings()
    llm = LLMClient()
    return SessionService(
        session_repo=SessionRepository(db),
        message_repo=MessageRepository(db),
        context_window=ContextWindowManager(llm_client=llm, model=settings.llm.default_model),
        prompt_builder=SystemPromptBuilder(llm_client=llm),
        llm_client=llm,
        model=settings.llm.default_model,
    )


ServiceDep = Annotated[SessionService, Depends(get_session_service)]


@router.post("", response_model=SessionRead, status_code=201)
async def create_session(
    data: SessionCreate,
    service: ServiceDep,
    tenant_id: TenantDep,
    user_id: UserDep,
) -> SessionRead:
    return await service.create_session(
        tenant_id=tenant_id,
        user_id=user_id,
        data=data,
    )


@router.get("", response_model=SessionList)
async def list_sessions(
    service: ServiceDep,
    tenant_id: TenantDep,
    user_id: uuid.UUID | None = Query(None, description="Filter by user ID"),
    status: str | None = Query(None, description="Filter by status (active, archived)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> SessionList:
    return await service.list_sessions(
        tenant_id=tenant_id,
        user_id=user_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/{session_id}", response_model=SessionRead)
async def get_session(
    session_id: uuid.UUID,
    service: ServiceDep,
) -> SessionRead:
    session = await service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/{session_id}", response_model=SessionRead)
async def update_session(
    session_id: uuid.UUID,
    data: SessionUpdate,
    service: ServiceDep,
) -> SessionRead:
    session = await service.update_session(session_id, data)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete(
    "/{session_id}",
    status_code=204,
    dependencies=[require_permission(Permission.SESSIONS_DELETE)],
)
async def archive_session(
    session_id: uuid.UUID,
    service: ServiceDep,
) -> None:
    session = await service.archive_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/{session_id}/fork", response_model=SessionRead, status_code=201)
async def fork_session(
    session_id: uuid.UUID,
    data: ForkRequest,
    service: ServiceDep,
) -> SessionRead:
    try:
        session = await service.fork_session(
            session_id=session_id,
            message_id=data.message_id,
            new_title=data.new_title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/{session_id}/rename", response_model=SessionRead)
async def rename_session(
    session_id: uuid.UUID,
    service: ServiceDep,
) -> SessionRead:
    session = await service.rename_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/{session_id}/messages", response_model=MessageList)
async def get_messages(
    session_id: uuid.UUID,
    service: ServiceDep,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    before_id: uuid.UUID | None = Query(None, description="Get messages before this ID"),
    after_id: uuid.UUID | None = Query(None, description="Get messages after this ID"),
) -> MessageList:
    return await service.get_messages(
        session_id=session_id,
        page=page,
        page_size=page_size,
        before_id=before_id,
        after_id=after_id,
    )


@router.post("/{session_id}/messages", response_model=MessageRead, status_code=201)
async def add_message(
    session_id: uuid.UUID,
    data: MessageCreate,
    service: ServiceDep,
) -> MessageRead:
    return await service.add_message(session_id, data)
