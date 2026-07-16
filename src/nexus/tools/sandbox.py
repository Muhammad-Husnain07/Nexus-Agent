"""Sandbox — host whitelist, log masking, request body size limits.

Gated by ``settings.tool.sandbox_enabled``.
"""

from __future__ import annotations

import fnmatch
from typing import Any

from pydantic import BaseModel, Field

SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset(
    {"authorization", "api_key", "api-key", "x-api-key", "apikey", "token", "secret"}
)

MAX_REQUEST_BYTES: int = 1_000_000


class SandboxBlockedError(Exception):
    """Raised when a tool execution is blocked by the sandbox."""

    def __init__(self, host: str, allowed_hosts: list[str]) -> None:
        self.host = host
        self.allowed_hosts = allowed_hosts
        super().__init__(f"Host '{host}' is not in allowed_hosts whitelist")


class SandboxConfig(BaseModel):
    """Sandbox configuration derived from ``ToolSettings``."""

    enabled: bool = Field(default=False, description="Enable sandboxed execution")
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["*"], description="Allowed external hosts (glob patterns)"
    )
    max_request_bytes: int = Field(
        default=MAX_REQUEST_BYTES, ge=1, description="Max request body size in bytes"
    )


def check_allowed_host(url: str, allowed_hosts: list[str]) -> None:
    """Raise ``SandboxBlockedError`` if the URL host is not in the whitelist.

    Supports glob patterns (``*``, ``?``) via ``fnmatch``. A single ``*``
    allows all hosts.
    """
    from urllib.parse import urlparse  # noqa: PLC0415

    parsed = urlparse(url)
    host = parsed.hostname or url

    if "*" in allowed_hosts:
        return

    for pattern in allowed_hosts:
        if fnmatch.fnmatch(host, pattern):
            return

    raise SandboxBlockedError(host, allowed_hosts)


def mask_sensitive_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``data`` with sensitive field values redacted.

    Sensitive fields are identified by a case-insensitive match against
    ``SENSITIVE_FIELD_NAMES``.
    """
    result: dict[str, Any] = {}
    for k, v in data.items():
        if k.lower() in SENSITIVE_FIELD_NAMES:
            result[k] = "***"
        elif isinstance(v, dict):
            result[k] = mask_sensitive_fields(v)
        else:
            result[k] = v
    return result
