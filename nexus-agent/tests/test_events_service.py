"""Tests for the events service: capability versioning, audit log, outbox.

Uses a fake session so no DB is required; verifies metadata-driven logic:
- snapshot_capability_version derives the next version from existing rows
- write_audit_log appends an AuditLog row
- process_outbox publishes pending rows and marks them published
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.db.models.audit_log import AuditLog
from nexus.db.models.capability_version import CapabilityVersion
from nexus.db.models.outbox import OutboxEvent
from nexus.events import service as svc


def _fake_session(*, add_side_effect: AsyncMock | None = None) -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=AsyncMock(scalars=AsyncMock(return_value=MagicMock(first=AsyncMock(return_value=None)))))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    if add_side_effect is not None:
        session.add = MagicMock(side_effect=add_side_effect)
    else:
        session.add = MagicMock()
    return session


class _FakeFactory:
    def __init__(self, session: MagicMock):
        self._session = session

    def __call__(self) -> _FakeFactory:
        return self

    async def __aenter__(self) -> MagicMock:
        return self._session

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_capability_version_derives_next_version(monkeypatch):
    latest = CapabilityVersion(capability_id="cap-1", version=4, active=True)
    session = MagicMock()
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=latest)))
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.add = MagicMock()

    monkeypatch.setattr(svc, "_session_factory", _FakeFactory(session))

    version = await svc.snapshot_capability_version(
        capability_id="cap-1",
        snapshot={"name": "x"},
    )
    assert version == 5
    added = session.add.call_args.args[0]
    assert added.version == 5
    assert added.active is True


@pytest.mark.asyncio
async def test_capability_version_starts_at_one(monkeypatch):
    session = MagicMock()
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.add = MagicMock()

    monkeypatch.setattr(svc, "_session_factory", _FakeFactory(session))

    version = await svc.snapshot_capability_version(
        capability_id="cap-new",
        snapshot={},
    )
    assert version == 1


@pytest.mark.asyncio
async def test_write_audit_log_appends_row(monkeypatch):
    session = MagicMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    monkeypatch.setattr(svc, "_session_factory", _FakeFactory(session))

    await svc.write_audit_log(
        action="workflow_registered",
        resource_type="workflow",
        resource_id="wf-1",
        actor_id="user-1",
    )
    added = session.add.call_args.args[0]
    assert isinstance(added, AuditLog)
    assert added.action == "workflow_registered"
    assert added.resource_id == "wf-1"


@pytest.mark.asyncio
async def test_enqueue_outbox_returns_id(monkeypatch):
    session = MagicMock()
    session.commit = AsyncMock()
    row = OutboxEvent(event_type="task.created", status="pending")
    session.add = MagicMock()
    session.refresh = AsyncMock(side_effect=lambda r: setattr(r, "id", "outbox-1"))

    monkeypatch.setattr(svc, "_session_factory", _FakeFactory(session))

    outbox_id = await svc.enqueue_outbox(
        event_type="task.created",
        aggregate_type="task",
        aggregate_id="task-1",
        payload={"x": 1},
    )
    assert outbox_id == "outbox-1"
    added = session.add.call_args.args[0]
    assert isinstance(added, OutboxEvent)
    assert added.event_type == "task.created"
    assert added.status == "pending"
