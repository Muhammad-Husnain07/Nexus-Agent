"""C4/P0-C secrets + redaction tests.

Covers: the auth_ref allowlist (secret-exfiltration channel closed) and
the production boot gate (AUTH_MODE=none refused in production).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pytest

from nexus.tools.sandbox import SandboxConfig, mask_sensitive_fields


class _FakeTool:
    def __init__(self, auth_type: str, auth_ref: str | None) -> None:
        self.name = "auth_tool"
        self.id = uuid.uuid4()
        self.endpoint_url = "https://api.example.com/op"
        self.http_method = "GET"
        self.input_schema = {}
        self.output_schema = None
        self.tool_type = "http"
        self.validation_rules = {}
        self.rate_limit_per_minute = None
        self.idempotent = False
        self.auth_type = auth_type
        self.auth_ref = auth_ref
        self.mcp_server_url = None


class TestAuthRefAllowlist:
    @pytest.fixture(autouse=True)
    def _no_redis(self, monkeypatch):
        monkeypatch.setattr("nexus.tools.executor.get_redis_client", lambda: None)

    def _executor(self, monkeypatch, allowlist: list[str]):
        from nexus.config.settings import get_settings
        from nexus.tools.executor import ToolExecutor

        settings = get_settings()
        monkeypatch.setattr(settings.tools, "auth_ref_allowlist", allowlist)
        return ToolExecutor(
            sandbox_config=SandboxConfig(allowed_hosts=["*"]),
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                follow_redirects=False,
            ),
        )

    def test_arbitrary_env_ref_denied(self, monkeypatch):
        """A tool pointing its auth_ref at ANY env var is denied unless
        allowlisted — the exfiltration channel is closed by default."""
        os.environ["ATTACKER_SENSITIVE_ENV"] = "super-secret-value"
        try:
            executor = self._executor(monkeypatch, allowlist=[])
            headers = asyncio.run(executor._resolve_auth(_FakeTool("bearer", "ATTACKER_SENSITIVE_ENV")))
            assert headers == {}, "un-allowlisted env refs must never resolve"
        finally:
            os.environ.pop("ATTACKER_SENSITIVE_ENV", None)

    def test_allowlisted_env_ref_resolves(self, monkeypatch):
        os.environ["NEXUS_AUTH_REF_TEST"] = "s3cret-value"
        try:
            executor = self._executor(monkeypatch, allowlist=["NEXUS_AUTH_REF_TEST"])
            headers = asyncio.run(executor._resolve_auth(_FakeTool("bearer", "NEXUS_AUTH_REF_TEST")))
            assert headers.get("Authorization") == "Bearer s3cret-value"
        finally:
            os.environ.pop("NEXUS_AUTH_REF_TEST", None)

    def test_no_auth_type_no_headers(self, monkeypatch):
        executor = self._executor(monkeypatch, allowlist=[])
        headers = asyncio.run(executor._resolve_auth(_FakeTool("none", None)))
        assert headers == {}


class TestRedaction:
    def test_sensitive_fields_masked_recursively(self):
        data = {
            "ok": True,
            "authorization": "Bearer hunter2",
            "nested": {"api_key": "sk-secret", "safe": "x"},
            "list": [{"token": "abc"}, {"name": "ok"}],
        }
        masked = mask_sensitive_fields(data)
        assert masked["authorization"] == "***"
        assert masked["nested"]["api_key"] == "***"
        assert masked["nested"]["safe"] == "x"
        assert masked["list"][0]["token"] == "***"
        assert masked["list"][1]["name"] == "ok"


class TestProductionBootGate:
    def test_production_with_no_auth_refuses_to_start(self, monkeypatch):
        from nexus.api.main import create_app
        from nexus.config.settings import get_settings

        monkeypatch.setenv("NEXUS_ENV", "production")
        settings = get_settings()
        monkeypatch.setattr(settings.auth, "mode", "none")
        with pytest.raises(RuntimeError, match="AUTH_MODE"):
            create_app()

    def test_production_with_auth_starts(self, monkeypatch):
        from nexus.api.main import create_app
        from nexus.config.settings import get_settings

        monkeypatch.setenv("NEXUS_ENV", "production")
        settings = get_settings()
        monkeypatch.setattr(settings.auth, "mode", "jwt")
        app = create_app()
        assert app is not None
