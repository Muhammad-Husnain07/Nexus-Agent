"""C3/P0-C — centralized session-ownership enforcement.

The tenant boundary: a session (and everything reachable through it —
checkpoints, messages, memory rows, long-running workflows, workflow
instances, WebSockets) belongs to the identity that created it. Every
API surface that addresses a session by id goes through this gate.

Legacy rows (user_id NULL, pre-migration) remain open — the documented
dev posture; production deployments backfill ownership in the migration.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request

from nexus.providers.auth.base import Identity


def identity_from_request(request: Request) -> Identity:
    """The verified caller identity (anonymous in auth mode ``none``)."""
    identity = getattr(request.state, "identity", None)
    if identity is None or not isinstance(identity, Identity):
        return Identity(user_id="anonymous")
    return identity


def session_owner_ok(identity: Identity, session_row: Any) -> bool:
    """True when the identity may access the session.

    A session is accessible when it has no recorded owner (legacy row) or
    its owner is the caller. ``anonymous`` in mode ``none`` owns exactly
    the sessions it created.
    """
    owner = getattr(session_row, "user_id", None)
    if owner is None:
        return True
    return str(owner) == str(identity.user_id)


async def require_session_access(
    request: Request,
    session_id: uuid.UUID | str,
) -> Any:
    """Fetch the session row and enforce ownership (C3/P0-C).

    Raises:
        HTTPException 404: no such session.
        HTTPException 403: the session belongs to another identity.
    Returns:
        The Session row.
    """
    from nexus.db.base import async_session  # noqa: PLC0415
    from nexus.sessions.repository import SessionRepository  # noqa: PLC0415

    identity = identity_from_request(request)
    async with async_session() as db_session:
        repo = SessionRepository(db_session)
        row = await repo.get(uuid.UUID(str(session_id)))
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session_owner_ok(identity, row):
        raise HTTPException(
            status_code=403,
            detail="This session belongs to another user",
        )
    return row


async def accessible_session_ids(request: Request) -> list[uuid.UUID]:
    """Session ids the caller may access (own sessions + legacy NULL rows)."""
    from sqlalchemy import select  # noqa: PLC0415

    from nexus.db.base import async_session  # noqa: PLC0415
    from nexus.db.models.session import Session as SessionModel  # noqa: PLC0415

    identity = identity_from_request(request)
    async with async_session() as db_session:
        stmt = select(SessionModel.id).where(
            (SessionModel.user_id == str(identity.user_id))
            | (SessionModel.user_id.is_(None))
        )
        result = await db_session.execute(stmt)
        return [row[0] for row in result.all()]
