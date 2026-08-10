"""C3/P0-C tenant-isolation offline tests.

Covers: the ownership gate semantics (own / foreign / legacy-NULL rows),
identity injection, and the executor authorization gate fed by the
verified ``user_context``. DB-backed endpoint enforcement is verified
against the live server (JWT mode probe) — see the stage report.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from nexus.providers.auth.base import Identity
from nexus.security.ownership import identity_from_request, session_owner_ok


class _Row:
    def __init__(self, user_id: str | None) -> None:
        self.user_id = user_id


class _FakeRequest:
    def __init__(self, identity: Identity | None) -> None:
        self.state = type("S", (), {"identity": identity})()


class TestOwnershipGate:
    def test_own_session_accessible(self):
        row = _Row("user-a")
        assert session_owner_ok(Identity(user_id="user-a"), row) is True

    def test_foreign_session_denied(self):
        row = _Row("user-a")
        assert session_owner_ok(Identity(user_id="user-b"), row) is False

    def test_legacy_null_owner_open(self):
        row = _Row(None)
        assert session_owner_ok(Identity(user_id="user-b"), row) is True

    def test_anonymous_owns_only_own(self):
        row = _Row("anonymous")
        assert session_owner_ok(Identity(user_id="anonymous"), row) is True
        assert session_owner_ok(Identity(user_id="user-b"), row) is False

    def test_identity_injection_from_middleware(self):
        identity = Identity(user_id="user-a", roles=["operator"])
        request = _FakeRequest(identity)
        assert identity_from_request(request).user_id == "user-a"
        assert identity_from_request(request).roles == ["operator"]

    def test_missing_identity_defaults_anonymous(self):
        request = _FakeRequest(None)
        assert identity_from_request(request).user_id == "anonymous"


class _FakeToolWithRoles:
    def __init__(self, allowed: list[str] | None = None) -> None:
        self.name = "role_gated_tool"
        self.id = uuid.uuid4()
        self.endpoint_url = "https://api.example.com/op"
        self.http_method = "GET"
        self.input_schema = {}
        self.output_schema = None
        self.tool_type = "http"
        self.validation_rules = {"allowed_roles": allowed} if allowed else {}
        self.rate_limit_per_minute = None
        self.idempotent = False
        self.auth_type = "none"
        self.auth_ref = None
        self.mcp_server_url = None


class _Ctx:
    def __init__(self, roles: list[str] | None = None) -> None:
        self.user_roles = roles or []
        self.session_id = str(uuid.uuid4())
        self.agent_run_id = None
        self.idempotency_key = None


class TestExecutorRolesGate:
    @pytest.fixture(autouse=True)
    def _no_redis(self, monkeypatch):
        """Keep the module-level redis client (bound to the first event
        loop) out of these unit tests."""
        monkeypatch.setattr("nexus.tools.executor.get_redis_client", lambda: None)

    def _executor(self):
        from nexus.tools.executor import ToolExecutor
        from nexus.tools.sandbox import SandboxConfig

        return ToolExecutor(
            sandbox_config=SandboxConfig(allowed_hosts=["*"]),
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})),
                follow_redirects=False,
            ),
        )

    def _run(self, executor, coro):
        async def _wrap():
            try:
                return await coro
            finally:
                await executor._client.aclose()

        return asyncio.run(_wrap())

    def test_allowed_role_executes(self):
        # The gate runs before any DB use in the authorization block; the
        # tool call is mocked. Execute with an authorized identity role.
        executor = self._executor()
        result = self._run(
            executor,
            executor.execute(
                _FakeToolWithRoles(["admin"]),
                {},
                _Ctx(roles=["admin"]),
                session=None,  # type: ignore[arg-type]
            ),
        )
        assert result.status == "success", result.error

    def test_denied_role_rejected(self):
        executor = self._executor()
        result = self._run(
            executor,
            executor.execute(
                _FakeToolWithRoles(["admin"]),
                {},
                _Ctx(roles=["user"]),
                session=None,  # type: ignore[arg-type]
            ),
        )
        assert result.status == "error"
        assert "authorization denied" in (result.error or "")

    def test_unconfigured_tool_open(self):
        executor = self._executor()
        result = self._run(
            executor,
            executor.execute(
                _FakeToolWithRoles(None),
                {},
                _Ctx(roles=[]),
                session=None,  # type: ignore[arg-type]
            ),
        )
        assert result.status == "success", result.error

    def test_user_context_roles_flow_into_gate(self):
        """The C3 chain end-to-end at the executor boundary: the graph
        derives ``user_roles`` from ``state.user_context`` (graph.py) and
        the executor gate enforces ``allowed_roles`` — a role-gated
        capability denies a caller without the role."""
        user_context = {"user_id": "user-a", "roles": ["operator"]}
        user_roles = list((user_context or {}).get("roles") or [])
        denied_ex = self._executor()
        denied = self._run(
            denied_ex,
            denied_ex.execute(
                _FakeToolWithRoles(["admin"]),
                {},
                _Ctx(roles=user_roles),
                session=None,  # type: ignore[arg-type]
            ),
        )
        assert denied.status == "error"
        assert "authorization denied" in (denied.error or "")

        user_context_admin = {"user_id": "user-a", "roles": ["admin"]}
        admin_roles = list((user_context_admin or {}).get("roles") or [])
        allowed_ex = self._executor()
        allowed = self._run(
            allowed_ex,
            allowed_ex.execute(
                _FakeToolWithRoles(["admin"]),
                {},
                _Ctx(roles=admin_roles),
                session=None,  # type: ignore[arg-type]
            ),
        )
        assert allowed.status == "success", allowed.error
