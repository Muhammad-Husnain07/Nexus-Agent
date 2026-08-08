"""ArtifactRegistry — durable, versioned artifact service (Phase 8).

Artifacts are immutable after publication: a new execution produces a NEW
revision row; the in-session ``ArtifactGraph`` remains the fast view over the
durable registry (reads hit memory, writes persist first).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import select

from nexus.db.base import async_session
from nexus.db.models.artifact_registry import ArtifactRecord

logger = structlog.get_logger("nexus.artifacts.registry")


class ArtifactRegistry:
    """DB-backed artifact registry (schemas, versions, relationships, lifecycle)."""

    @staticmethod
    async def register(
        *,
        session_id: str | None,
        capability_id: str,
        tool_name: str,
        artifact_type: str,
        schema_version: str,
        artifact_revision: int,
        data: dict[str, Any],
        execution_id: str | None = None,
        parent_artifact_id: uuid.UUID | None = None,
        status: str = "created",
    ) -> uuid.UUID:
        """Publish an immutable artifact revision (best-effort durable)."""
        artifact_id = uuid.uuid4()
        try:
            async with async_session() as session:
                session.add(ArtifactRecord(
                    id=artifact_id,
                    session_id=uuid.UUID(session_id) if session_id else None,
                    capability_id=capability_id,
                    tool_name=tool_name,
                    type=artifact_type,
                    schema_version=schema_version,
                    artifact_revision=artifact_revision,
                    status=status,
                    parent_artifact_id=parent_artifact_id,
                    execution_id=execution_id,
                    data=data,
                ))
                await session.commit()
        except Exception as exc:
            logger.warning("artifact_registry.register_failed", error=str(exc)[:200])
        return artifact_id

    @staticmethod
    async def set_lifecycle(artifact_id: uuid.UUID, status: str) -> bool:
        """Transition lifecycle (created → promoted → archived)."""
        try:
            async with async_session() as session:
                row = await session.get(ArtifactRecord, artifact_id)
                if row is None:
                    return False
                row.status = status
                await session.commit()
                return True
        except Exception as exc:
            logger.warning("artifact_registry.lifecycle_failed", error=str(exc)[:200])
            return False

    @staticmethod
    async def list_by_type(artifact_type: str, limit: int = 50) -> list[dict[str, Any]]:
        try:
            async with async_session() as session:
                rows = (
                    await session.execute(
                        select(ArtifactRecord)
                        .where(ArtifactRecord.type == artifact_type)
                        .order_by(ArtifactRecord.created_at.desc())
                        .limit(limit)
                    )
                ).scalars().all()
                return [ArtifactRegistry._to_dict(r) for r in rows]
        except Exception as exc:
            logger.warning("artifact_registry.list_failed", error=str(exc)[:200])
            return []

    @staticmethod
    async def list_by_execution(execution_id: str) -> list[dict[str, Any]]:
        try:
            async with async_session() as session:
                rows = (
                    await session.execute(
                        select(ArtifactRecord)
                        .where(ArtifactRecord.execution_id == execution_id)
                        .order_by(ArtifactRecord.created_at.desc())
                    )
                ).scalars().all()
                return [ArtifactRegistry._to_dict(r) for r in rows]
        except Exception as exc:
            logger.warning("artifact_registry.execution_list_failed", error=str(exc)[:200])
            return []

    @staticmethod
    def _to_dict(row: ArtifactRecord) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "session_id": str(row.session_id) if row.session_id else None,
            "capability_id": row.capability_id,
            "tool_name": row.tool_name,
            "type": row.type,
            "schema_version": row.schema_version,
            "artifact_revision": row.artifact_revision,
            "status": row.status,
            "parent_artifact_id": str(row.parent_artifact_id) if row.parent_artifact_id else None,
            "execution_id": row.execution_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
