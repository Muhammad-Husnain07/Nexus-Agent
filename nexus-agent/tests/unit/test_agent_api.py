"""Unit tests for agent API schemas and the session state endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.agent.schemas import (
    AgentInvokeRequest,
    AgentInvokeResponse,
    AgentResumeResponse,
    AgentStateResponse,
    ApprovalAction,
)
from nexus.api.chat import router as chat_router

# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestAgentInvokeRequest:
    """AgentInvokeRequest schema validation."""

    def test_valid_request(self) -> None:
        sid = uuid.uuid4()
        req = AgentInvokeRequest(session_id=sid, message="hello")
        assert req.session_id == sid
        assert req.message == "hello"

    def test_empty_message_raises(self) -> None:
        with pytest.raises(ValueError, match="String should have at least 1 character"):
            AgentInvokeRequest(session_id=uuid.uuid4(), message="")

    def test_serialises(self) -> None:
        sid = uuid.uuid4()
        req = AgentInvokeRequest(session_id=sid, message="test")
        data = req.model_dump(mode="json")
        assert data["session_id"] == str(sid)
        assert data["message"] == "test"


def test_empty_message_invalid() -> None:
    with pytest.raises(Exception, match="String should have at least 1 character"):
        AgentInvokeRequest(session_id=uuid.uuid4(), message="")


class TestAgentInvokeResponse:
    """AgentInvokeResponse schema."""

    def test_defaults(self) -> None:
        sid = uuid.uuid4()
        resp = AgentInvokeResponse(session_id=sid)
        assert resp.session_id == sid
        assert resp.final_response is None
        assert resp.interrupted is False
        assert resp.events == []

    def test_with_values(self) -> None:
        sid = uuid.uuid4()
        resp = AgentInvokeResponse(
            session_id=sid,
            final_response="done",
            interrupted=True,
            approval_payload={"tool": "test"},
            events=[{"node": "finalize", "update": {"final_response": "done"}}],
        )
        assert resp.final_response == "done"
        assert resp.interrupted is True
        assert len(resp.events) == 1


class TestApprovalAction:
    """ApprovalAction schema."""

    def test_approve(self) -> None:
        action = ApprovalAction(approved=True)
        assert action.approved is True
        assert action.modified_inputs is None

    def test_reject(self) -> None:
        action = ApprovalAction(approved=False)
        assert action.approved is False

    def test_with_modified_inputs(self) -> None:
        action = ApprovalAction(approved=True, modified_inputs={"key": "value"})
        assert action.modified_inputs == {"key": "value"}


class TestAgentResumeResponse:
    """AgentResumeResponse schema."""

    def test_completed(self) -> None:
        sid = uuid.uuid4()
        resp = AgentResumeResponse(session_id=sid, status="completed", final_response="done")
        assert resp.status == "completed"
        assert resp.final_response == "done"


class TestAgentStateResponse:
    """AgentStateResponse schema."""

    def test_paused(self) -> None:
        sid = uuid.uuid4()
        resp = AgentStateResponse(
            session_id=sid,
            status="paused",
            current_node="execute_step",
            pending_approval={"tool_name": "test_tool"},
        )
        assert resp.status == "paused"
        assert resp.pending_approval["tool_name"] == "test_tool"


# ---------------------------------------------------------------------------
# Session state endpoint tests (via chat router)
# ---------------------------------------------------------------------------


def _make_mock_state_snapshot(next_nodes: list[str], values: dict | None = None):
    """Create a mock LangGraph StateSnapshot."""
    snapshot = MagicMock()
    snapshot.next = tuple(next_nodes)
    snapshot.values = values or {}
    if values:
        snapshot.values = values
    else:
        snapshot.values = {}
    return snapshot


@pytest.fixture
def app() -> FastAPI:
    """Create a test FastAPI app with the chat router and mock state."""
    app = FastAPI()
    app.include_router(chat_router)

    from nexus.config.settings import AgentSettings, LLMSettings, ServerSettings, Settings

    app.state.settings = Settings(
        llm=LLMSettings(default_model="gpt-4o"),
        agent=AgentSettings(),
        server=ServerSettings(),
    )

    mock_registry = MagicMock()
    mock_registry.register = AsyncMock()
    mock_registry.search_semantic = AsyncMock(return_value=[])
    app.state.tool_registry = mock_registry

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """FastAPI TestClient."""
    with TestClient(app) as c:
        yield c


class TestSessionStateEndpoint:
    """GET /sessions/{session_id}/state"""

    def test_state_paused(self, client: TestClient) -> None:
        """Returns paused state when graph has interrupt."""
        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                ["execute_step"],
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "pending_approval": {"tool_name": "test"},
                },
            )
        )
        mock_graph.aget_state.return_value.values = {
            "messages": [{"role": "user", "content": "hi"}],
            "pending_approval": {"tool_name": "test"},
        }

        sid = str(uuid.uuid4())
        with patch("nexus.api.chat.AgentRunner._build_graph", return_value=mock_graph):
            resp = client.get(f"/sessions/{sid}/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"
        assert data["current_node"] == "execute_step"

    def test_state_completed(self, client: TestClient) -> None:
        """Returns completed state when graph has no next nodes."""
        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                [],
                {
                    "messages": [{"role": "user", "content": "hi"}],
                    "final_response": "All done.",
                },
            )
        )
        mock_graph.aget_state.return_value.values = {
            "messages": [{"role": "user", "content": "hi"}],
            "final_response": "All done.",
        }

        sid = str(uuid.uuid4())
        with patch("nexus.api.chat.AgentRunner._build_graph", return_value=mock_graph):
            resp = client.get(f"/sessions/{sid}/state")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_state_not_found(self, client: TestClient) -> None:
        """Returns 404 if checkpointer has no state for session."""
        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot([], {})
        )
        mock_graph.aget_state.return_value.values = {}

        sid = uuid.uuid4()
        with patch("nexus.api.chat.AgentRunner._build_graph", return_value=mock_graph):
            resp = client.get(f"/sessions/{sid}/state")
        assert resp.status_code == 404
