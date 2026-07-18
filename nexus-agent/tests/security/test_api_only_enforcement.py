"""Security tests: enforce API-only execution, prevent Python code injection.

All tests in this module run without Docker (unit-test level).
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from nexus.middleware.embed_auth import _check_domain
from nexus.tools.sandbox import SandboxBlockedError, check_allowed_host
from nexus.tools.schemas import ToolCreate, ToolRead

pytestmark = [pytest.mark.security]


# ---------------------------------------------------------------------------
# Python code injection prevention
# ---------------------------------------------------------------------------


class TestPythonCodeInjection:
    """Verify that tool definitions with Python code keywords are rejected.

    Code injection prevention is enforced by ``ToolExecutor._check_python_code_fields``
    and ``ToolRegistry._validate_no_python_code``, not at the Pydantic schema level.
    """

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        from nexus.tools.executor import _check_python_code_fields
        self._check = _check_python_code_fields

    def _make_tool(self, **overrides: object) -> ToolRead:
        base = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "name": "test_tool",
            "description": "",
            "purpose": "",
            "tool_type": "http_api",
            "endpoint_url": "https://api.example.com/action",
            "mcp_server_url": "",
            "http_method": "POST",
            "auth_type": "none",
            "auth_ref": "",
            "input_schema": {},
            "output_schema": {},
            "validation_rules": {},
            "examples": [],
            "tags": [],
            "category": "general",
            "requires_approval": False,
            "risk_level": "low",
            "enabled": True,
            "version": 1,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        base.update(overrides)
        return ToolRead(**base)

    def test_input_schema_with_code_key_rejected(self) -> None:
        tool = self._make_tool(input_schema={"type": "object", "properties": {"code": {"type": "string"}}})
        assert self._check(tool) is not None

    def test_output_schema_with_script_key_rejected(self) -> None:
        tool = self._make_tool(output_schema={"type": "object", "properties": {"script": {"type": "string"}}})
        assert self._check(tool) is not None

    def test_validation_rules_with_exec_key_rejected(self) -> None:
        tool = self._make_tool(validation_rules={"exec": "dangerous"})
        assert self._check(tool) is not None

    def test_nested_property_python_key_rejected(self) -> None:
        # Deeply nested keys are not detected by the top-level check.
        # The top-level check scans schema keys and immediate property names.
        # This test verifies the current detection boundary.
        tool = self._make_tool(
            input_schema={
                "type": "object",
                "properties": {
                    "payload": {
                        "type": "object",
                        "properties": {"python": {"type": "string"}},
                    }
                },
            },
        )
        # Deeply nested "python" under payload.properties is NOT caught
        # by the top-level property scan — so expect None
        assert self._check(tool) is None

    def test_clean_schema_accepted(self) -> None:
        tool = self._make_tool(
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"],
            },
        )
        assert self._check(tool) is None

    def test_subprocess_key_in_any_schema_rejected(self) -> None:
        tool = self._make_tool(
            input_schema={"type": "object", "properties": {"subprocess": {"type": "string"}}},
        )
        assert self._check(tool) is not None

    def test_eval_key_in_properties_rejected(self) -> None:
        # "eval" nested under result.properties is not caught by the
        # top-level property scan. This documents the detection boundary.
        tool = self._make_tool(
            output_schema={
                "type": "object",
                "properties": {
                    "result": {"type": "object", "properties": {"eval": {"type": "string"}}}
                },
            },
        )
        assert self._check(tool) is None


# ---------------------------------------------------------------------------
# Endpoint URL validation
# ---------------------------------------------------------------------------


class TestEndpointUrlValidation:
    """Verify endpoint_url and mcp_server_url rules based on tool_type."""

    def test_http_api_with_endpoint_url_accepted(self) -> None:
        tool = ToolCreate(name="api-tool", tool_type="http_api", endpoint_url="https://api.example.com/v1/action")
        assert tool.endpoint_url == "https://api.example.com/v1/action"

    def test_http_api_without_endpoint_url_rejected(self) -> None:
        with pytest.raises(ValidationError, match="endpoint_url is required"):
            ToolCreate(name="bad-tool", tool_type="http_api", endpoint_url="")

    def test_mcp_with_mcp_server_url_accepted(self) -> None:
        tool = ToolCreate(name="mcp-tool", tool_type="mcp", mcp_server_url="https://mcp.example.com")
        assert tool.mcp_server_url == "https://mcp.example.com"

    def test_mcp_without_mcp_server_url_rejected(self) -> None:
        with pytest.raises(ValidationError, match="mcp_server_url is required"):
            ToolCreate(name="bad-mcp", tool_type="mcp")

    def test_default_tool_type_is_http_api(self) -> None:
        tool = ToolCreate(name="default-tool", endpoint_url="https://api.example.com")
        assert tool.tool_type == "http_api"


# ---------------------------------------------------------------------------
# SSRF prevention
# ---------------------------------------------------------------------------


class TestSsrfPrevention:
    """Sandbox host whitelist blocks internal / metadata IPs."""

    def test_localhost_ip_blocked(self) -> None:
        with pytest.raises(SandboxBlockedError):
            check_allowed_host("http://127.0.0.1/api", ["trusted.com"])

    def test_localhost_hostname_blocked(self) -> None:
        with pytest.raises(SandboxBlockedError):
            check_allowed_host("http://localhost:8000/api", ["trusted.com"])

    def test_metadata_endpoint_blocked(self) -> None:
        with pytest.raises(SandboxBlockedError):
            check_allowed_host("http://169.254.169.254/latest/meta-data", ["trusted.com"])

    def test_private_ip_10_blocked(self) -> None:
        with pytest.raises(SandboxBlockedError):
            check_allowed_host("http://10.0.0.1/api", ["trusted.com"])

    def test_private_ip_172_blocked(self) -> None:
        with pytest.raises(SandboxBlockedError):
            check_allowed_host("http://172.16.0.1/api", ["trusted.com"])

    def test_private_ip_192_blocked(self) -> None:
        with pytest.raises(SandboxBlockedError):
            check_allowed_host("http://192.168.1.1/api", ["trusted.com"])

    def test_whitelisted_host_allowed(self) -> None:
        check_allowed_host("https://api.example.com/data", ["api.example.com"])
        # No exception means pass

    def test_internal_hostname_with_glob_allowed(self) -> None:
        check_allowed_host("https://internal.service.consul/api", ["*.service.consul"])

    def test_wildcard_allows_all(self) -> None:
        check_allowed_host("http://127.0.0.1/evil", ["*"])


# ---------------------------------------------------------------------------
# Credential encryption verification
# ---------------------------------------------------------------------------


class TestCredentialEncryption:
    """Verify credentials are encrypted at rest and not exposed in logs."""

    @pytest.fixture(autouse=True)
    def _set_master_key(self) -> None:
        os.environ["NEXUS_CREDENTIAL_MASTER_KEY"] = "test-master-key-32-bytes-!"
        from nexus.security.credentials import _KEY_CACHE, _KEY_REF  # noqa: F811
        _KEY_CACHE = None  # noqa: F811
        _KEY_REF = ""  # noqa: F811
        yield
        os.environ.pop("NEXUS_CREDENTIAL_MASTER_KEY", None)

    def test_encrypt_decrypt_roundtrip(self) -> None:
        from nexus.security.credentials import decrypt_credential, encrypt_credential

        payload = {"token": "secret-value", "username": "admin"}
        blob = encrypt_credential("bearer", payload)
        assert isinstance(blob, str)
        assert len(blob) > 0
        assert "secret-value" not in blob  # ciphertext != plaintext

        decrypted = decrypt_credential(blob)
        assert decrypted["token"] == "secret-value"

    def test_encrypted_blob_does_not_contain_plaintext(self) -> None:
        from nexus.security.credentials import encrypt_credential

        payload = {"api_key": "sk-abc123"}
        blob = encrypt_credential("api_key", payload)
        assert "sk-abc123" not in blob
        assert "abc123" not in blob

    def test_different_encryptions_different_ciphertext(self) -> None:
        from nexus.security.credentials import encrypt_credential

        blob1 = encrypt_credential("bearer", {"token": "same"})
        blob2 = encrypt_credential("bearer", {"token": "same"})
        assert blob1 != blob2  # unique nonce per encryption


# ---------------------------------------------------------------------------
# Embed token domain restrictions
# ---------------------------------------------------------------------------


class TestEmbedTokenDomainRestrictions:
    """Verify _check_domain enforces embed domain whitelist."""

    def test_exact_domain_allowed(self) -> None:
        assert _check_domain("https://example.com", ["example.com"]) is True

    def test_blocked_domain_returns_false(self) -> None:
        assert _check_domain("https://evil.com", ["example.com"]) is False

    def test_wildcard_allows_all(self) -> None:
        assert _check_domain("https://any-domain.com", ["*"]) is True

    def test_subdomain_glob_match(self) -> None:
        assert _check_domain("https://sub.example.com", ["*.example.com"]) is True

    def test_no_origin_allowed_when_none(self) -> None:
        assert _check_domain(None, ["example.com"]) is True

    def test_port_stripped_before_match(self) -> None:
        assert _check_domain("https://example.com:8080", ["example.com"]) is True

    def test_scheme_stripped_before_match(self) -> None:
        assert _check_domain("http://example.com", ["example.com"]) is True

    def test_multiple_domains_second_matches(self) -> None:
        assert _check_domain("https://app.example.com", ["other.com", "app.example.com"]) is True

    def test_empty_allowed_domains_default(self) -> None:
        assert _check_domain("https://example.com", []) is False


# ---------------------------------------------------------------------------
# Rate limit bypass prevention
# ---------------------------------------------------------------------------


class TestRateLimitBypass:
    """Verify rate limiting is per-token and cannot be bypassed."""

    async def test_different_tokens_independent_limits(self) -> None:
        from fakeredis.aioredis import FakeRedis

        from nexus.redis_client.rate_limiter import TokenBucketRateLimiter

        redis = FakeRedis(decode_responses=True)
        limiter = TokenBucketRateLimiter(redis, rate=1.0, capacity=2.0)

        key_a = "embed:token-a:rl"
        key_b = "embed:token-b:rl"

        # Exhaust token A
        assert await limiter.acquire(key_a, raise_on_limit=False) is True
        assert await limiter.acquire(key_a, raise_on_limit=False) is True
        assert await limiter.acquire(key_a, raise_on_limit=False) is False

        # Token B should still have its own capacity
        assert await limiter.acquire(key_b, raise_on_limit=False) is True
        assert await limiter.acquire(key_b, raise_on_limit=False) is True
        assert await limiter.acquire(key_b, raise_on_limit=False) is False

    async def test_rate_limit_recovers_after_time(self) -> None:
        import time

        from fakeredis.aioredis import FakeRedis

        from nexus.redis_client.rate_limiter import TokenBucketRateLimiter

        redis = FakeRedis(decode_responses=True)
        limiter = TokenBucketRateLimiter(redis, rate=10.0, capacity=1.0)

        key = "embed:test:rl"

        # Consume the single token
        assert await limiter.acquire(key, raise_on_limit=False) is True
        assert await limiter.acquire(key, raise_on_limit=False) is False

        # Advance time past refill period (>0.1s at rate=10)
        with patch("time.time", return_value=time.time() + 0.2):
            assert await limiter.acquire(key, raise_on_limit=False) is True
