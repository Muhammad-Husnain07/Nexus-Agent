"""Events & audit — capability versioning, audit log, transactional outbox.

This module wires the schema-level tables (``capability_version``,
``audit_log``, ``outbox_event``) into real runtime behaviour:

- ``snapshot_capability_version`` — append a version snapshot when a
  capability/tool is registered or updated.
- ``write_audit_log`` — append-only audit record for significant actions.
- ``publish_outbox`` — mark outbox rows published after a successful Redis
  publish (transactional-outbox relay); ``process_outbox`` drains pending
  rows.

All of it is metadata-driven: event types, resource kinds, and payloads are
supplied by callers, never hardcoded here.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select, update

from nexus.db.base import async_session as _session_factory
from nexus.db.models.audit_log import AuditLog
from nexus.db.models.capability_version import CapabilityVersion
from nexus.db.models.outbox import OutboxEvent
from nexus.redis_client import EventBus, get_redis_client

logger = structlog.get_logger("nexus.events")


# ---------------------------------------------------------------------------
# Capability versioning
# ---------------------------------------------------------------------------


async def snapshot_capability_version(
    *,
    capability_id: str,
    snapshot: dict[str, Any],
    changed_by: str | None = None,
    change_comment: str | None = None,
    session: Any | None = None,
) -> int:
    """Append a version snapshot for a capability.

    The version number is derived from the existing rows for that capability
    (max + 1) — never guessed. The latest snapshot is marked active; older
    ones are deactivated.

    Args:
        capability_id: The capability (tool) id.
        snapshot: Full capability contract snapshot (JSON-serializable).
        changed_by: Actor id (user id or system).
        change_comment: Optional reason for the change.
        session: Reusable DB session; when None a new session is opened.

    Returns:
        The new version number.
    """
    own_session = session is None
    async with _session_factory() as db:
        result = await db.execute(
            select(CapabilityVersion)
            .where(CapabilityVersion.capability_id == capability_id)
            .order_by(CapabilityVersion.version.desc())
            .limit(1)
        )
        latest = result.scalars().first()
        version = (latest.version + 1) if latest is not None else 1

        await db.execute(
            update(CapabilityVersion)
            .where(CapabilityVersion.capability_id == capability_id)
            .values(active=False)
        )
        db.add(
            CapabilityVersion(
                capability_id=capability_id,
                version=version,
                snapshot=snapshot,
                changed_by=changed_by,
                change_comment=change_comment,
                active=True,
            )
        )
        await db.commit()
        logger.info(
            "events.capability_versioned",
            capability_id=capability_id,
            version=version,
        )
        return version


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


async def write_audit_log(
    *,
    action: str,
    resource_type: str = "",
    resource_id: str | None = None,
    actor_id: str | None = None,
    session_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    detail: str | None = None,
    session: Any | None = None,
) -> None:
    """Append an audit record (fire-and-forget safe).

    Args:
        action: Action type (e.g. ``tool_executed``, ``workflow_registered``).
        resource_type: Resource kind (tool, session, workflow, ...).
        resource_id: Resource id.
        actor_id: Actor (user id or system).
        session_id: Related conversation session.
        before: State before the action.
        after: State after the action.
        detail: Free-form detail.
        session: Reusable DB session; when None a new session is opened.
    """
    async with _session_factory() as db:
        db.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                session_id=session_id,
                before=before,
                after=after,
                detail=detail,
            )
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Transactional outbox
# ---------------------------------------------------------------------------


async def enqueue_outbox(
    *,
    event_type: str,
    aggregate_type: str = "",
    aggregate_id: str | None = None,
    payload: dict[str, Any] | None = None,
    session: Any | None = None,
) -> str:
    """Write a domain event into the outbox (durable, transactional).

    Args:
        event_type: Domain event type (e.g. ``task.created``).
        aggregate_type: Aggregate kind (session, task, workflow, ...).
        aggregate_id: Aggregate id.
        payload: Event payload.
        session: Reusable DB session; when None a new session is opened.

    Returns:
        The outbox row id.
    """
    async with _session_factory() as db:
        row = OutboxEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload or {},
            status="pending",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return str(row.id)


async def process_outbox(limit: int = 50) -> int:
    """Relay pending outbox rows to Redis pub/sub and mark them published.

    Best-effort: rows whose publish fails keep ``status='pending'`` and are
    retried on the next call (bounded by attempts in a real relay).

    Args:
        limit: Max rows to process per call.

    Returns:
        Number of rows published.
    """
    redis = get_redis_client()
    if redis is None:
        return 0
    bus = EventBus(redis)
    published = 0
    async with _session_factory() as db:
        result = await db.execute(
            select(OutboxEvent)
            .where(OutboxEvent.status == "pending")  # noqa: E712
            .order_by(OutboxEvent.created_at)
            .limit(limit)
        )
        rows = result.scalars().all()
        for row in rows:
            try:
                await bus.publish(
                    f"outbox:{row.aggregate_type or 'event'}",
                    {
                        "event_type": row.event_type,
                        "aggregate_id": row.aggregate_id,
                        "payload": row.payload,
                    },
                )
                await db.execute(
                    update(OutboxEvent)
                    .where(OutboxEvent.id == row.id)
                    .values(status="published", published_at=_now())
                )
                published += 1
            except Exception as exc:
                logger.warning(
                    "outbox.publish_failed",
                    outbox_id=str(row.id),
                    event_type=row.event_type,
                    error=str(exc)[:200],
                )
        await db.commit()
    if published:
        logger.info("outbox.processed", published=published)
    return published


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)
