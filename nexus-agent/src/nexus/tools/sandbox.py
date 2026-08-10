"""Sandbox — host whitelist + SSRF hardening for HTTP calls only, log
masking, request body size limits. Does NOT support Python code execution.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from pydantic import BaseModel, Field

from nexus.config.settings import get_settings


def _get_sensitive_fields() -> frozenset[str]:
    """Return sensitive field names from settings, or fallback defaults."""
    try:
        return frozenset(get_settings().tools.sensitive_field_names)
    except Exception:
        return frozenset({"authorization", "api_key", "api-key", "x-api-key", "apikey", "token", "secret"})


def _get_max_request_bytes() -> int:
    """Return max request body size from settings, or fallback default."""
    try:
        return get_settings().tools.max_request_bytes
    except Exception:
        return 1_000_000


class SandboxBlockedError(Exception):
    """Raised when an HTTP tool call is blocked by the sandbox host whitelist."""

    def __init__(self, host: str, allowed_hosts: list[str]) -> None:
        self.host = host
        self.allowed_hosts = allowed_hosts
        super().__init__(f"Host '{host}' is not in allowed_hosts whitelist")


class SandboxConfig(BaseModel):
    """Sandbox configuration derived from ``ToolSettings``."""

    enabled: bool = Field(default=True, description="Enable sandbox host whitelist enforcement")
    allowed_hosts: list[str] = Field(
        default_factory=list, description="Allowed external hosts (empty = block all)"
    )
    max_request_bytes: int = Field(
        default_factory=_get_max_request_bytes, ge=1, description="Max request body size in bytes"
    )


def check_allowed_host(url: str, allowed_hosts: list[str],
                       enforce_ssrf: bool = False) -> None:
    """Raise ``SandboxBlockedError`` if the URL host is not in the whitelist.

    Supports glob patterns (``*``, ``?``) via ``fnmatch``. An empty list
    blocks all hosts.

    SSRF HARDENING (P0): ``enforce_ssrf=True`` (the DYNAMIC-endpoint class
    — a resolved URL whose host differs from the operator-registered host,
    i.e. the host was influenced by tool inputs) additionally blocks the
    request when the scheme is not http(s) or ANY resolved address is
    private/link-local (loopback, RFC1918, CGNAT, 169.254.x.x incl. the
    cloud metadata IP 169.254.169.254, IPv6 ::1 / fc00::/7 / fe80::/10).
    Operator-registered static endpoints are trusted by configuration.
    """
    from urllib.parse import urlparse  # noqa: PLC0415

    parsed = urlparse(url)
    host = parsed.hostname or url
    scheme = (parsed.scheme or "").lower()

    if enforce_ssrf and scheme not in ("http", "https"):
        raise SandboxBlockedError(host, allowed_hosts)

    if not allowed_hosts:
        raise SandboxBlockedError(host, allowed_hosts)

    if "*" not in allowed_hosts:
        matched = any(fnmatch.fnmatch(host, pattern) for pattern in allowed_hosts)
        if not matched:
            raise SandboxBlockedError(host, allowed_hosts)

    # SSRF: literal-IP and resolved-address validation — mandatory for the
    # dynamic-endpoint class (a name resolving to an internal address is
    # blocked at resolution time).
    if enforce_ssrf:
        _block_private_addresses(host)


def _block_private_addresses(host: str) -> None:
    """Raise ``SandboxBlockedError`` when the host resolves to (or IS) a
    private/loopback/link-local/reserved address."""
    import ipaddress  # noqa: PLC0415
    import socket  # noqa: PLC0415

    candidates: list[str] = [host]
    try:
        for info in socket.getaddrinfo(host, None):
            addr = info[4][0]
            if addr not in candidates:
                candidates.append(addr)
    except Exception:
        # Unresolvable host — the HTTP layer surfaces the connection
        # failure; nothing here to validate.
        pass  # noqa: S110

    for candidate in candidates:
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        # C1/P0-C: unspecified (0.0.0.0 / :: — binds loopback on most
        # hosts), private, loopback, link-local and reserved are all
        # blocked. IPv4-mapped IPv6 (::ffff:127.0.0.1) is evaluated on
        # its embedded IPv4 address too.
        mapped = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) else None
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_unspecified
            or (
                mapped is not None
                and (
                    mapped.is_private or mapped.is_loopback
                    or mapped.is_link_local or mapped.is_reserved
                    or mapped.is_unspecified
                )
            )
        ):
            raise SandboxBlockedError(host, [])


def mask_sensitive_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``data`` with sensitive field values redacted.

    Sensitive fields are identified by a case-insensitive match against
    the configured ``sensitive_field_names`` setting. Recurses into nested
    dicts AND lists (C4/P0-C — payloads often carry secret-bearing lists).
    """
    sensitive = _get_sensitive_fields()

    def _mask(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: "***" if k.lower() in sensitive else _mask(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [_mask(v) for v in value]
        return value

    return _mask(data)
