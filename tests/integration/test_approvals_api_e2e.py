"""HTTP-layer E2E tests for the /api/v1/approvals endpoints.

Tests the full approval lifecycle through the HTTP API with mocked DB
and graph dependencies:
- GET /pending/{session_id}: list with auto-expiry
- GET /{approval_id}: single approval status
- POST /{approval_id}/decide: approve → resumes graph → completes
- POST /{approval_id}/decide: reject → persists → graph notified
- POST /{approval_id}/decide: edit → validates → persists
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.integration]

from nexus.api.approvals import router as approvals_router


@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.include_router(approvals_router)
    return _app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as c:
        yield c


def _make_mock_session():
    """Create a mock async_session context manager."""
    sess = AsyncMock()
    sess.__aenter__ = AsyncMock(return_value=sess)
    sess.__aexit__ = AsyncMock(return_value=None)
    sess.commit = AsyncMock()
    return sess


def _make_approval_row(
    approval_id: uuid.UUID | None = None,
    agent_run_id: uuid.UUID | None = None,
    session_id: str = "00000000-0000-0000-0000-000000000001",
    status: str = "pending",
    created_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = approval_id or uuid.uuid4()
    row.agent_run_id = agent_run_id or uuid.uuid4()
    row.status = status
    row.tool_call = {"session_id": session_id, "name": "test_tool"}
    row.decision_payload = None
    row.created_at = created_at or datetime.now(UTC)
    row.decided_at = None
    return row


class _AsyncIter:
    """Helper: wraps items into an async iterator."""

    def __init__(self, items: list) -> None:
        self._items = items
        self._idx = 0

    def __aiter__(self) -> _AsyncIter:
        return self

    async def __anext__(self):
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        val = self._items[self._idx]
        self._idx += 1
        return val


def _make_empty_astream():
    return lambda *a, **kw: _AsyncIter([])


class TestApprovalsAPIE2E:
    """HTTP-layer E2E tests for the approvals API."""

    def test_list_pending_empty(self, client: TestClient) -> None:
        """GET /pending returns empty list when no approvals exist."""
        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.find = AsyncMock(return_value=[])
        mock_session.__aenter__.return_value = mock_session

        with patch("nexus.api.approvals.async_session", return_value=mock_session):
            with patch("nexus.api.approvals.GenericRepository", return_value=mock_repo):
                sid = uuid.uuid4()
                resp = client.get(f"/api/v1/approvals/pending/{sid}")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_pending_with_rows(self, client: TestClient) -> None:
        """GET /pending returns pending approvals for the session."""
        session_id = "00000000-0000-0000-0000-000000000001"
        approval_id = uuid.uuid4()
        mock_approval = _make_approval_row(
            approval_id=approval_id,
            session_id=session_id,
            created_at=datetime.now(UTC),
        )
        other_session_approval = _make_approval_row(
            session_id="00000000-0000-0000-0000-000000009999",
            created_at=datetime.now(UTC),
        )

        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.find = AsyncMock(return_value=[mock_approval, other_session_approval])
        mock_session.__aenter__.return_value = mock_session

        with patch("nexus.api.approvals.async_session", return_value=mock_session):
            with patch("nexus.api.approvals.GenericRepository", return_value=mock_repo):
                resp = client.get(f"/api/v1/approvals/pending/{session_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1  # only the one matching session_id
        assert data[0]["id"] == str(approval_id)

    def test_list_auto_rejects_expired(self, client: TestClient) -> None:
        """GET /pending auto-rejects approvals older than timeout."""
        session_id = "00000000-0000-0000-0000-000000000001"
        expired_id = uuid.uuid4()
        expired = _make_approval_row(
            approval_id=expired_id,
            session_id=session_id,
            created_at=datetime.now(UTC) - timedelta(hours=48),
        )
        valid = _make_approval_row(
            session_id=session_id,
            created_at=datetime.now(UTC),
        )

        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.find = AsyncMock(return_value=[expired, valid])

        update_mock_session = _make_mock_session()
        update_mock_repo = MagicMock()
        update_mock_repo.update = AsyncMock(return_value=None)

        mock_session.__aenter__.return_value = mock_session

        with patch("nexus.api.approvals.async_session") as mock_async_session:
            mock_async_session.side_effect = [mock_session, update_mock_session]
            with patch("nexus.api.approvals.GenericRepository") as mock_generic_repo:
                mock_generic_repo.side_effect = [mock_repo, update_mock_repo]
                resp = client.get(f"/api/v1/approvals/pending/{session_id}")

        assert resp.status_code == 200
        data = resp.json()
        # Only the valid (non-expired) one is returned
        assert len(data) == 1
        # The expired one was updated to rejected
        update_mock_repo.update.assert_awaited_once()
        update_kwargs = update_mock_repo.update.call_args.kwargs
        assert update_kwargs["status"] == "rejected"

    def test_get_approval_found(self, client: TestClient) -> None:
        """GET /{id} returns approval details."""
        approval_id = uuid.uuid4()
        mock_approval = _make_approval_row(approval_id=approval_id)

        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_approval)
        mock_session.__aenter__.return_value = mock_session

        with patch("nexus.api.approvals.async_session", return_value=mock_session):
            with patch("nexus.api.approvals.GenericRepository", return_value=mock_repo):
                resp = client.get(f"/api/v1/approvals/{approval_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(approval_id)
        assert data["status"] == "pending"

    def test_get_approval_not_found(self, client: TestClient) -> None:
        """GET /{id} returns 404 for unknown approval."""
        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_session.__aenter__.return_value = mock_session

        with patch("nexus.api.approvals.async_session", return_value=mock_session):
            with patch("nexus.api.approvals.GenericRepository", return_value=mock_repo):
                resp = client.get(f"/api/v1/approvals/{uuid.uuid4()}")

        assert resp.status_code == 404

    def test_decide_approve_resumes_graph(self, client: TestClient) -> None:
        """POST /{id}/decide with approve persists and resumes."""
        session_id = "00000000-0000-0000-0000-000000000001"
        approval_id = uuid.uuid4()
        mock_approval = _make_approval_row(
            approval_id=approval_id,
            session_id=session_id,
        )

        mock_graph = MagicMock()
        mock_graph.astream = _make_empty_astream()
        mock_graph.aget_state = AsyncMock()
        mock_graph.aget_state.return_value.next = ()  # completed

        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_approval)
        mock_repo.update = AsyncMock(return_value=None)
        mock_session.__aenter__.return_value = mock_session

        with (
            patch("nexus.api.approvals.async_session", return_value=mock_session),
            patch("nexus.api.approvals.GenericRepository", return_value=mock_repo),
            patch("nexus.api.approvals.graph_cache.get_graph", return_value=mock_graph),
            patch("nexus.api.approvals.graph_cache.has_graph", return_value=True),
        ):
            resp = client.post(
                f"/api/v1/approvals/{approval_id}/decide",
                json={"action": "approve"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "approve"
        # Verify the DB was updated
        mock_repo.update.assert_awaited_once()
        update_kwargs = mock_repo.update.call_args.kwargs
        assert update_kwargs["status"] == "approve"

    def test_decide_reject(self, client: TestClient) -> None:
        """POST /{id}/decide with reject persists rejection."""
        session_id = "00000000-0000-0000-0000-000000000001"
        approval_id = uuid.uuid4()
        mock_approval = _make_approval_row(
            approval_id=approval_id,
            session_id=session_id,
        )
        mock_graph = MagicMock()
        mock_graph.astream = _make_empty_astream()
        mock_graph.aget_state = AsyncMock()
        mock_graph.aget_state.return_value.next = ()

        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_approval)
        mock_repo.update = AsyncMock(return_value=None)
        mock_session.__aenter__.return_value = mock_session

        with (
            patch("nexus.api.approvals.async_session", return_value=mock_session),
            patch("nexus.api.approvals.GenericRepository", return_value=mock_repo),
            patch("nexus.api.approvals.graph_cache.has_graph", return_value=True),
            patch("nexus.api.approvals.graph_cache.get_graph", return_value=mock_graph),
        ):
            resp = client.post(
                f"/api/v1/approvals/{approval_id}/decide",
                json={"action": "reject", "comment": "Not needed"},
            )

        assert resp.status_code == 200
        assert resp.json()["decision"] == "reject"
        update_kwargs = mock_repo.update.call_args.kwargs
        assert update_kwargs["status"] == "reject"

    def test_decide_edit(self, client: TestClient) -> None:
        """POST /{id}/decide with edit persists edited inputs."""
        session_id = "00000000-0000-0000-0000-000000000001"
        approval_id = uuid.uuid4()
        mock_approval = _make_approval_row(
            approval_id=approval_id,
            session_id=session_id,
        )
        mock_graph = MagicMock()
        mock_graph.astream = _make_empty_astream()
        mock_graph.aget_state = AsyncMock()
        mock_graph.aget_state.return_value.next = ()

        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_approval)
        mock_repo.update = AsyncMock(return_value=None)
        mock_session.__aenter__.return_value = mock_session

        edited_inputs = {"arg1": "edited_val"}
        with (
            patch("nexus.api.approvals.async_session", return_value=mock_session),
            patch("nexus.api.approvals.GenericRepository", return_value=mock_repo),
            patch("nexus.api.approvals.graph_cache.has_graph", return_value=True),
            patch("nexus.api.approvals.graph_cache.get_graph", return_value=mock_graph),
        ):
            resp = client.post(
                f"/api/v1/approvals/{approval_id}/decide",
                json={"action": "edit", "edited_inputs": edited_inputs},
            )

        assert resp.status_code == 200
        assert resp.json()["decision"] == "edit"
        update_kwargs = mock_repo.update.call_args.kwargs
        assert update_kwargs["status"] == "edit"

    def test_decide_already_decided(self, client: TestClient) -> None:
        """POST /{id}/decide returns 409 if already decided."""
        approval_id = uuid.uuid4()
        mock_approval = _make_approval_row(
            approval_id=approval_id, status="approved"
        )

        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_approval)
        mock_session.__aenter__.return_value = mock_session

        with patch("nexus.api.approvals.async_session", return_value=mock_session):
            with patch("nexus.api.approvals.GenericRepository", return_value=mock_repo):
                resp = client.post(
                    f"/api/v1/approvals/{approval_id}/decide",
                    json={"action": "approve"},
                )

        assert resp.status_code == 409
        assert "already" in resp.json()["detail"].lower()

    def test_decide_not_found(self, client: TestClient) -> None:
        """POST /{id}/decide returns 404 for unknown approval."""
        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_session.__aenter__.return_value = mock_session

        with patch("nexus.api.approvals.async_session", return_value=mock_session):
            with patch("nexus.api.approvals.GenericRepository", return_value=mock_repo):
                resp = client.post(
                    f"/api/v1/approvals/{uuid.uuid4()}/decide",
                    json={"action": "approve"},
                )

        assert resp.status_code == 404

    def test_decide_session_gone(self, client: TestClient) -> None:
        """POST /{id}/decide returns 410 if graph cache evicted."""
        session_id = "00000000-0000-0000-0000-000000000001"
        approval_id = uuid.uuid4()
        mock_approval = _make_approval_row(
            approval_id=approval_id,
            session_id=session_id,
        )

        mock_session = _make_mock_session()
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_approval)
        mock_session.__aenter__.return_value = mock_session

        with patch("nexus.api.approvals.async_session", return_value=mock_session):
            with patch("nexus.api.approvals.GenericRepository", return_value=mock_repo):
                with patch("nexus.api.approvals.graph_cache.has_graph", return_value=False):
                    resp = client.post(
                        f"/api/v1/approvals/{approval_id}/decide",
                        json={"action": "approve"},
                    )

        assert resp.status_code == 410
