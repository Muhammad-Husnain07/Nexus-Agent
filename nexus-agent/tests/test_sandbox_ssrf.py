"""SSRF hardening tests (P0) — the sandbox's dynamic-endpoint address-space
validation must block private/loopback/link-local/reserved destinations
while allowing operator-registered public endpoints.
"""

from __future__ import annotations

import pytest

from nexus.tools.sandbox import SandboxBlockedError, check_allowed_host


def _blocked(url: str, hosts: list[str], enforce_ssrf: bool = True) -> bool:
    try:
        check_allowed_host(url, hosts, enforce_ssrf=enforce_ssrf)
        return False
    except SandboxBlockedError:
        return True


def test_loopback_blocked():
    assert _blocked("http://127.0.0.1:8000/x", ["*"])
    assert _blocked("http://localhost/x", ["*"])
    assert _blocked("http://[::1]/x", ["*"])


def test_cloud_metadata_blocked():
    assert _blocked("http://169.254.169.254/latest/meta-data", ["*"])


def test_private_ranges_blocked():
    assert _blocked("http://10.0.0.1/x", ["*"])
    assert _blocked("http://172.16.5.5/x", ["*"])
    assert _blocked("http://192.168.1.1/x", ["*"])


def test_non_http_scheme_blocked():
    assert _blocked("ftp://example.com/x", ["*"])
    assert _blocked("file:///etc/passwd", ["*"])


def test_public_host_allowed():
    assert not _blocked("https://jsonplaceholder.typicode.com/posts/1", ["*"])


def test_whitelist_still_enforced_for_static_endpoints():
    # Static registered endpoints (operator-configured) keep the whitelist
    # as their only gate — no strict SSRF.
    assert _blocked("https://other.example.com/x", ["jsonplaceholder.typicode.com"],
                    enforce_ssrf=False)
    assert not _blocked("https://jsonplaceholder.typicode.com/posts/1",
                        ["jsonplaceholder.typicode.com"], enforce_ssrf=False)
