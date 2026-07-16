"""Unit tests for sandbox — host whitelist, log masking."""

from __future__ import annotations

import pytest

from nexus.tools.sandbox import (
    SandboxBlockedError,
    check_allowed_host,
    mask_sensitive_fields,
)


class TestCheckAllowedHost:
    def test_wildcard_allows_all(self) -> None:
        check_allowed_host("http://evil.com/api", ["*"])

    def test_exact_match_allowed(self) -> None:
        check_allowed_host("https://api.example.com/data", ["api.example.com"])

    def test_glob_pattern_allowed(self) -> None:
        check_allowed_host("https://api.example.com/data", ["*.example.com"])

    def test_blocked_host_raises(self) -> None:
        with pytest.raises(SandboxBlockedError) as exc:
            check_allowed_host("http://malicious.net", ["trusted.com"])
        assert "malicious.net" in str(exc.value)


class TestMaskSensitiveFields:
    def test_masks_authorization(self) -> None:
        result = mask_sensitive_fields({"Authorization": "Bearer secret123"})
        assert result["Authorization"] == "***"

    def test_masks_api_key_case_insensitive(self) -> None:
        result = mask_sensitive_fields({"X-API-Key": "abc123"})
        assert result["X-API-Key"] == "***"

    def test_does_not_mask_other_fields(self) -> None:
        result = mask_sensitive_fields({"name": "test", "value": 42})
        assert result["name"] == "test"
        assert result["value"] == 42

    def test_recursive_masking(self) -> None:
        result = mask_sensitive_fields({"nested": {"Authorization": "secret"}})
        assert result["nested"]["Authorization"] == "***"
