"""Tests for ToolExecutor HTTPX client lifecycle and sandbox host checking."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nexus.tools.executor import ToolExecutor
from nexus.tools.sandbox import SandboxBlockedError, check_allowed_host


class TestHttpClientLifecycle:
    """HTTPX client reuse and cleanup."""

    def test_shared_client_across_instances(self) -> None:
        """Two ToolExecutor instances with same http_client share the client."""
        client = MagicMock(spec=httpx.AsyncClient)
        ex1 = ToolExecutor(http_client=client)
        ex2 = ToolExecutor(http_client=client)
        assert ex1._client is ex2._client
        assert ex1._client is client

    def test_default_client_created_if_none(self) -> None:
        """ToolExecutor(http_client=None) creates its own client."""
        ex = ToolExecutor()
        assert isinstance(ex._client, httpx.AsyncClient)
        # Clean up to avoid resource warnings
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(ex.close())
        loop.close()

    def test_client_aclose_called(self) -> None:
        """close() calls aclose on the client."""
        client = MagicMock(spec=httpx.AsyncClient)
        client.aclose = AsyncMock()
        ex = ToolExecutor(http_client=client)
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(ex.close())
        loop.close()
        client.aclose.assert_awaited_once()


class TestSandbox:
    """Sandbox host allow/block rules."""

    def test_sandbox_blocks_evil_host(self) -> None:
        """Host not in allowed_hosts raises error."""
        with pytest.raises(SandboxBlockedError, match="evil"):
            check_allowed_host("http://evil.com", ["api.example.com"])

    def test_sandbox_allows_whitelisted_host(self) -> None:
        """Host in allowed_hosts passes."""
        check_allowed_host("http://api.example.com/path", ["api.example.com"])

    def test_sandbox_blocks_when_empty(self) -> None:
        """Empty allowed_hosts blocks all hosts."""
        with pytest.raises(SandboxBlockedError, match="any.com"):
            check_allowed_host("http://any.com", [])

    def test_sandbox_allows_wildcard(self) -> None:
        """Wildcard pattern *.example.com matches subdomains."""
        check_allowed_host("http://a.internal.com", ["*.internal.com"])

    def test_sandbox_wildcard_does_not_match_root(self) -> None:
        """Wildcard *.example.com does not match example.com itself."""
        with pytest.raises(SandboxBlockedError):
            check_allowed_host("http://internal.com", ["*.internal.com"])

    def test_sandbox_allows_wildcard_star(self) -> None:
        """Single * allows all hosts."""
        check_allowed_host("http://anything.com", ["*"])

    def test_sandbox_handles_port_variation(self) -> None:
        """Host with port strips port before matching."""
        check_allowed_host("https://api.example.com:8080/path", ["api.example.com"])
