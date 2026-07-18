"""AuditLogger — writes AuditLog rows for every privileged action.

Integrates with the existing ``AuditLog`` model to record:
- Tool registration / deletion
- Approval decisions
- Configuration changes
- Authentication events (login, token refresh, revoke)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import Request

from nexus.db.base import async_session
from nexus.db.models.audit import AuditLog

logger = structlog.get_logger("nexus.security.audit")


class AuditLogger:
    """Logs security-relevant events to the ``AuditLog`` table.

    Usage::

        await AuditLogger.log(
            action="tools:register",
            actor_id=user_id,
            resource_type="tool",
            resource_id=tool_id,
            payload={"name": "send_email"},
            request=request,
        )
    """

    @staticmethod
    async def log(
        action: str,
        actor_id: uuid.UUID | None = None,
        resource_type: str = "",
        resource_id: str = "",
        payload: dict[str, Any] | None = None,
        request: Request | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> None:
        """Write an audit log entry.

        Args:
            action: Machine-readable action name (e.g. ``tools:register``).
            actor_id: UUID of the user who performed the action.
            resource_type: Type of resource affected (``tool``, ``session``, etc.).
            resource_id: Identifier of the resource (UUID string or other).
            payload: Arbitrary JSON-serialisable event details.
            request: The HTTP request (used to extract IP address).
            tenant_id: Tenant UUID (falls back to request tenant context).
        """
        ip = ""
        if request is not None:
            ip = request.client.host if request.client else ""
            if tenant_id is None:
                from nexus.db.context import get_tenant

                tenant_id = get_tenant()

        if tenant_id is None:
            logger.warning("audit.no_tenant", action=action)
            return

        try:
            async with async_session() as session:
                entry = AuditLog(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    actor_id=actor_id or uuid.uuid4(),
                    action=action,
                    resource_type=resource_type or "unknown",
                    resource_id=resource_id or "",
                    payload=payload or {},
                    ip=ip,
                    created_at=datetime.now(UTC),
                )
                session.add(entry)
                await session.commit()
            logger.info("audit.logged", action=action, resource_type=resource_type)
        except Exception as exc:
            logger.error("audit.write_failed", action=action, error=str(exc))
