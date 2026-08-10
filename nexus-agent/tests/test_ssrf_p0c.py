"""C1/P0-C SSRF adversarial tests — the FINAL destination is the boundary.

Covers: template-host substitution, redirect hops, 0.0.0.0 / :: / IPv4-
mapped IPv6, MCP server_url, and the /tools/{id}/test endpoint.
Deterministic — no live server, no real network (httpx MockTransport).
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from nexus.tools.sandbox import SandboxBlockedError, SandboxConfig, check_allowed_host

# ---------------------------------------------------------------------------
# Sandbox hardening: unspecified + IPv4-mapped addresses
# ---------------------------------------------------------------------------


class TestSandboxHardening:
    @pytest.mark.parametrize(
        "url",
        [
            "http://0.0.0.0/x",
            "http://127.0.0.1/x",
            "http://[::]/x",
            "http://[::1]/x",
            "http://[::ffff:127.0.0.1]/x",
            "http://169.254.169.254/x",
            "http://10.0.0.1/x",
            "http://192.168.1.1/x",
            "http://172.16.0.1/x",
        ],
    )
    def test_internal_destinations_blocked(self, url):
        with pytest.raises(SandboxBlockedError):
            check_allowed_host(url, ["*"], enforce_ssrf=True)

    def test_public_destination_allowed(self):
        check_allowed_host("http://api.example.com/x", ["*"], enforce_ssrf=True)

    def test_non_http_scheme_blocked(self):
        with pytest.raises(SandboxBlockedError):
            check_allowed_host("file:///etc/passwd", ["*"], enforce_ssrf=True)
        with pytest.raises(SandboxBlockedError):
            check_allowed_host("gopher://169.254.169.254/", ["*"], enforce_ssrf=True)


# ---------------------------------------------------------------------------
# Executor: final-URL validation (template substitution + redirects)
# ---------------------------------------------------------------------------


class _FakeTool:
    def __init__(
        self,
        endpoint: str,
        method: str = "GET",
        schema: dict | None = None,
    ) -> None:
        self.name = "fake_tool"
        self.id = uuid.uuid4()
        self.endpoint_url = endpoint
        self.http_method = method
        self.input_schema = schema or {}
        self.output_schema = None
        self.tool_type = "http"


class TestExecutorFinalUrlValidation:
    def test_template_host_substitution_to_metadata_blocked(self):
        from nexus.tools.executor import ToolExecutor

        tool = _FakeTool("https://{host}/data")
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
            follow_redirects=False,
        )
        executor = ToolExecutor(
            sandbox_config=SandboxConfig(allowed_hosts=["*"]),
            http_client=client,
        )
        with pytest.raises(SandboxBlockedError):
            asyncio.run(
                executor._execute_http(
                    tool, {"host": "169.254.169.254"}, {},
                )
            )

    def test_template_host_substitution_to_private_blocked(self):
        from nexus.tools.executor import ToolExecutor

        tool = _FakeTool("https://{host}/data")
        executor = ToolExecutor(
            sandbox_config=SandboxConfig(allowed_hosts=["*"]),
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                follow_redirects=False,
            ),
        )
        with pytest.raises(SandboxBlockedError):
            asyncio.run(executor._execute_http(tool, {"host": "192.168.1.1"}, {}))

    def test_unwhitelisted_substituted_host_blocked(self):
        from nexus.tools.executor import ToolExecutor

        tool = _FakeTool("https://{host}/data")
        executor = ToolExecutor(
            sandbox_config=SandboxConfig(allowed_hosts=["api.example.com"]),
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                follow_redirects=False,
            ),
        )
        with pytest.raises(SandboxBlockedError):
            asyncio.run(executor._execute_http(tool, {"host": "evil.example.com"}, {}))

    def test_redirect_to_metadata_blocked_before_second_request(self):
        """The 302 hop to an internal address is re-validated — the second
        request must never be sent (transport records exactly one call)."""
        from nexus.tools.executor import ToolExecutor

        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(
                302,
                headers={"location": "http://169.254.169.254/steal"},
            )

        tool = _FakeTool("https://api.example.com/start")
        executor = ToolExecutor(
            sandbox_config=SandboxConfig(allowed_hosts=["*"]),
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                follow_redirects=False,
            ),
        )
        with pytest.raises(SandboxBlockedError):
            asyncio.run(executor._execute_http(tool, {}, {}))
        assert len(calls) == 1, "the redirect target must never be requested"

    def test_safe_redirect_is_followed_with_revalidation(self):
        from nexus.tools.executor import ToolExecutor

        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if "start" in str(request.url):
                return httpx.Response(
                    302, headers={"location": "https://api.example.com/final"}
                )
            return httpx.Response(200, json={"ok": True})

        tool = _FakeTool("https://api.example.com/start")
        executor = ToolExecutor(
            sandbox_config=SandboxConfig(allowed_hosts=["*"]),
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                follow_redirects=False,
            ),
        )
        response = asyncio.run(executor._execute_http(tool, {}, {}))
        assert response.status_code == 200
        assert len(calls) == 2

    def test_mcp_server_url_private_blocked(self):
        from nexus.tools.executor import ToolExecutor

        tool = _FakeTool("http://169.254.169.254/mcp")
        tool.tool_type = "mcp"
        tool.mcp_server_url = "http://169.254.169.254/mcp"
        executor = ToolExecutor(
            sandbox_config=SandboxConfig(allowed_hosts=["*"]),
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                follow_redirects=False,
            ),
        )
        result = asyncio.run(
            executor._execute_mcp(tool, {}, object(), None)  # type: ignore[arg-type]
        )
        assert result.status == "error"
        assert "allowed_hosts" in (result.error or "").lower()


class TestToolTestEndpointSsrF:
    def test_test_endpoint_blocks_metadata_ip(self, monkeypatch):
        from nexus.tools.registry import ToolRegistry

        class _FakeTool:
            id = uuid.uuid4()
            name = "t"
            endpoint_url = "http://169.254.169.254/x"
            http_method = "GET"
            rate_limit_per_minute = None
            input_schema = {}
            output_schema = None
            validation_rules = {}

        registry = ToolRegistry()  # type: ignore[abstract]
        result = asyncio.run(
            registry.test_http_connection(_FakeTool(), sample_input={})  # type: ignore[arg-type]
        )
        assert result.status == "error"
        assert "Sandbox blocked" in (result.error or "")
