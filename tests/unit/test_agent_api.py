"""Unit tests for agent API schemas and endpoints."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.agent import graph_cache
from nexus.agent.api import router as agent_router
from nexus.agent.schemas import (
    AgentInvokeRequest,
    AgentInvokeResponse,
    AgentResumeResponse,
    AgentStateResponse,
    ApprovalAction,
)

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
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """Create a test FastAPI app with the agent router and mock state."""
    app = FastAPI()
    app.include_router(agent_router)

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


def _make_mock_state_snapshot(next_nodes: list[str], values: dict | None = None):
    """Create a mock LangGraph StateSnapshot."""
    snapshot = MagicMock()
    snapshot.next = tuple(next_nodes)
    # Must be subscriptable like a dict
    snapshot.values = values or {}
    # Make items() work like dict.items() for .get() calls
    if values:
        snapshot.values = values
    else:
        snapshot.values = {}
    return snapshot


@pytest.fixture(autouse=True)
def clear_graph_cache():
    """Clear the shared graph cache before each test."""
    from nexus.agent.graph_cache import clear_all

    clear_all()


class TestInvokeEndpoint:
    """POST /api/v1/agent/invoke"""

    def test_happy_path(self, client: TestClient) -> None:
        """Synchronous invoke returns final_response."""
        import nexus.agent.api as agent_api_module

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(return_value=_make_mock_state_snapshot([]))

        async def _astream(*args: object, **kwargs: object):
            yield {
                "finalize": {
                    "final_response": "Task completed successfully.",
                    "_routing_decision": "finalize",
                }
            }

        mock_graph.astream = _astream

        with patch.object(agent_api_module, "_get_or_create_graph", return_value=mock_graph):
            sid = uuid.uuid4()
            resp = client.post(
                "/api/v1/agent/invoke",
                json={"session_id": str(sid), "message": "do something"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == str(sid)
        assert data["final_response"] == "Task completed successfully."
        assert data["interrupted"] is False

    def test_returns_interrupt(self, client: TestClient) -> None:
        """Returns interrupt=True when pending_approval is set."""
        import nexus.agent.api as agent_api_module

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(return_value=_make_mock_state_snapshot([]))

        async def _astream(*args: object, **kwargs: object):
            yield {
                "execute_step": {
                    "pending_approval": {
                        "type": "approval_required",
                        "tool_name": "write_file",
                        "inputs": {"path": "/tmp/test.txt"},
                    },
                    "_routing_decision": "continue",
                }
            }

        mock_graph.astream = _astream

        with patch.object(agent_api_module, "_get_or_create_graph", return_value=mock_graph):
            sid = uuid.uuid4()
            resp = client.post(
                "/api/v1/agent/invoke",
                json={"session_id": str(sid), "message": "write a file"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["interrupted"] is True
        assert data["approval_payload"] is not None
        assert data["approval_payload"]["tool_name"] == "write_file"

    def test_returns_existing_run(self, client: TestClient) -> None:
        """Returns interrupt if session already has a paused run."""
        import nexus.agent.api as agent_api_module

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                ["execute_step"],
                {"pending_approval": {"type": "approval_required", "tool_name": "test"}},
            )
        )

        with patch.object(agent_api_module, "_get_or_create_graph", return_value=mock_graph):
            sid = uuid.uuid4()
            resp = client.post(
                "/api/v1/agent/invoke",
                json={"session_id": str(sid), "message": "do it"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["interrupted"] is True
        assert data["approval_payload"] is not None

    def test_invoke_error(self, client: TestClient) -> None:
        """Returns error when graph astream raises."""
        import nexus.agent.api as agent_api_module

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(return_value=_make_mock_state_snapshot([]))

        async def _astream(*args: object, **kwargs: object):
            raise RuntimeError("LLM call failed")

        mock_graph.astream = _astream

        with patch.object(agent_api_module, "_get_or_create_graph", return_value=mock_graph):
            sid = uuid.uuid4()
            resp = client.post(
                "/api/v1/agent/invoke",
                json={"session_id": str(sid), "message": "do something"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is not None


class TestStreamEndpoint:
    """POST /api/v1/agent/stream"""

    def test_streams_events(self, client: TestClient) -> None:
        """SSE stream returns events."""
        import nexus.agent.api as agent_api_module

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(return_value=_make_mock_state_snapshot([]))

        async def _astream(*args: object, **kwargs: object):
            yield {
                "finalize": {
                    "final_response": "Done.",
                    "_routing_decision": "finalize",
                }
            }

        mock_graph.astream = _astream

        with patch.object(agent_api_module, "_get_or_create_graph", return_value=mock_graph):
            sid = uuid.uuid4()
            with client.stream(
                "POST",
                "/api/v1/agent/stream",
                json={"session_id": str(sid), "message": "hello"},
            ) as response:
                assert response.status_code == 200
                events = list(response.iter_lines())
                assert len(events) >= 2  # at least final_response + done

    def test_stream_interrupt(self, client: TestClient) -> None:
        """SSE stream sends interrupt event when pending_approval."""
        import nexus.agent.api as agent_api_module

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(return_value=_make_mock_state_snapshot([]))

        async def _astream(*args: object, **kwargs: object):
            yield {
                "execute_step": {
                    "pending_approval": {
                        "type": "approval_required",
                        "tool_name": "delete_file",
                    },
                    "_routing_decision": "continue",
                }
            }

        mock_graph.astream = _astream

        with patch.object(agent_api_module, "_get_or_create_graph", return_value=mock_graph):
            sid = uuid.uuid4()
            with client.stream(
                "POST",
                "/api/v1/agent/stream",
                json={"session_id": str(sid), "message": "delete file"},
            ) as response:
                assert response.status_code == 200
                all_text = ""
                for chunk in response.iter_raw():
                    if chunk:
                        all_text += chunk.decode("utf-8", errors="replace")
                assert "interrupt" in all_text
                assert "approval_required" in all_text

    def test_stream_existing_paused(self, client: TestClient) -> None:
        """Returns paused event immediately if session has existing interrupt."""
        import nexus.agent.api as agent_api_module

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                ["execute_step"],
                {"pending_approval": {"tool_name": "test"}},
            )
        )

        with patch.object(agent_api_module, "_get_or_create_graph", return_value=mock_graph):
            sid = uuid.uuid4()
            with client.stream(
                "POST",
                "/api/v1/agent/stream",
                json={"session_id": str(sid), "message": "do it"},
            ) as response:
                assert response.status_code == 200
                all_text = ""
                for chunk in response.iter_raw():
                    if chunk:
                        all_text += chunk.decode("utf-8", errors="replace")
                assert "paused" in all_text


class TestResumeEndpoint:
    """POST /api/v1/agent/{session_id}/resume"""

    def test_resume_approved(self, client: TestClient) -> None:
        """Resume with approved=True returns completed."""

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                ["execute_step"],
                {"pending_approval": {"tool_name": "test"}},
            )
        )

        async def _astream(*args: object, **kwargs: object):
            yield {
                "finalize": {
                    "final_response": "Completed after approval.",
                    "_routing_decision": "finalize",
                }
            }

        mock_graph.astream = _astream

        sid = str(uuid.uuid4())
        graph_cache.set_graph(sid, mock_graph)

        resp = client.post(
            f"/api/v1/agent/{sid}/approve",
            json={},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["final_response"] == "Completed after approval."

    def test_resume_rejected(self, client: TestClient) -> None:
        """Resume with approved=False skips the tool."""

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                ["execute_step"],
                {"pending_approval": {"tool_name": "test"}},
            )
        )

        async def _astream(*args: object, **kwargs: object):
            yield {
                "finalize": {
                    "final_response": "Tool was skipped.",
                    "_routing_decision": "finalize",
                }
            }

        mock_graph.astream = _astream

        sid = str(uuid.uuid4())
        graph_cache.set_graph(sid, mock_graph)

        resp = client.post(
            f"/api/v1/agent/{sid}/reject",
            json={},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_resume_graph_not_found(self, client: TestClient) -> None:
        """Returns 404 if no graph exists for session."""
        sid = uuid.uuid4()
        resp = client.post(f"/api/v1/agent/{sid}/approve", json={})
        assert resp.status_code == 404

    def test_resume_not_paused(self, client: TestClient) -> None:
        """Returns 400 if graph is not paused."""

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(return_value=_make_mock_state_snapshot([]))

        sid = str(uuid.uuid4())
        graph_cache.set_graph(sid, mock_graph)

        resp = client.post(f"/api/v1/agent/{sid}/approve", json={})
        assert resp.status_code == 400
        assert "not paused" in resp.json()["detail"]

    def test_edit_requires_modified_inputs(self, client: TestClient) -> None:
        """Edit endpoint requires modified_inputs in body."""

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                ["execute_step"],
                {"pending_approval": {"tool_name": "test"}},
            )
        )

        sid = str(uuid.uuid4())
        graph_cache.set_graph(sid, mock_graph)

        resp = client.post(f"/api/v1/agent/{sid}/edit", json={"approved": True})
        assert resp.status_code == 400

    def test_edit_with_modified_inputs(self, client: TestClient) -> None:
        """Edit endpoint resumes with modified inputs."""

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                ["execute_step"],
                {"pending_approval": {"tool_name": "test"}},
            )
        )

        async def _astream(*args: object, **kwargs: object):
            yield {
                "finalize": {
                    "final_response": "Edited and completed.",
                    "_routing_decision": "finalize",
                }
            }

        mock_graph.astream = _astream

        sid = str(uuid.uuid4())
        graph_cache.set_graph(sid, mock_graph)

        resp = client.post(
            f"/api/v1/agent/{sid}/edit",
            json={
                "approved": True,
                "modified_inputs": {"path": "/tmp/edited.txt"},
            },
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


class TestStateEndpoint:
    """GET /api/v1/agent/{session_id}/state"""

    def test_state_paused(self, client: TestClient) -> None:
        """Returns paused state when graph has interrupt."""

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                ["execute_step"],
                {"pending_approval": {"tool_name": "test"}},
            )
        )

        sid = str(uuid.uuid4())
        graph_cache.set_graph(sid, mock_graph)

        resp = client.get(f"/api/v1/agent/{sid}/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "paused"
        assert data["current_node"] == "execute_step"

    def test_state_completed(self, client: TestClient) -> None:
        """Returns completed state when graph has no next nodes."""

        mock_graph = MagicMock()
        mock_graph.aget_state = AsyncMock(
            return_value=_make_mock_state_snapshot(
                [], {"final_response": "All done."}
            )
        )

        sid = str(uuid.uuid4())
        graph_cache.set_graph(sid, mock_graph)

        resp = client.get(f"/api/v1/agent/{sid}/state")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_state_not_found(self, client: TestClient) -> None:
        """Returns 404 if no graph exists for session."""
        sid = uuid.uuid4()
        resp = client.get(f"/api/v1/agent/{sid}/state")
        assert resp.status_code == 404
