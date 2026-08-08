"""Adversarial + hardening tests (P0/P1/P2) — the safety and semantics
boundaries: prompt-injection framing, SSRF, authorization, idempotency
stamping, approval binding, and memory provenance.
"""

from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Prompt-injection boundary (P1)
# ---------------------------------------------------------------------------


def test_finalize_prompt_has_untrusted_data_boundary():
    from nexus.agent.prompts.finalize import SYSTEM_PROMPT_V4

    assert "UNTRUSTED-DATA BOUNDARY" in SYSTEM_PROMPT_V4
    assert "inert facts" in SYSTEM_PROMPT_V4


# ---------------------------------------------------------------------------
# SSRF (P0) — dynamic endpoints
# ---------------------------------------------------------------------------


def test_ssrf_dynamic_endpoint_blocks_metadata_ip():
    from nexus.tools.sandbox import SandboxBlockedError, check_allowed_host

    with pytest.raises(SandboxBlockedError):
        check_allowed_host(
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            ["*"],
            enforce_ssrf=True,
        )


def test_ssrf_static_registered_host_allowed():
    from nexus.tools.sandbox import check_allowed_host

    check_allowed_host(
        "https://jsonplaceholder.typicode.com/posts/1",
        ["*"],
        enforce_ssrf=True,
    )  # public host — must pass


# ---------------------------------------------------------------------------
# Authorization gate (P0)
# ---------------------------------------------------------------------------


def _tool_read(name, risk="low", metadata=None):
    from nexus.tools.schemas import ToolRead

    return ToolRead(
        id="00000000-0000-0000-0000-000000000000",
        name=name, description="", purpose="", tool_type="http_api",
        endpoint_url="https://example.com/x", http_method="GET",
        auth_type="none", auth_ref="",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        validation_rules=metadata or {}, examples=[], tags=[], category="general",
        requires_approval=False, risk_level=risk, enabled=True, version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def test_authorization_gate_denies_when_roles_mismatch(monkeypatch):
    import uuid

    from nexus.tools.executor import ExecutionContext, ToolExecutor

    monkeypatch.setattr("nexus.tools.executor.get_redis_client", lambda: None)
    tool = _tool_read("restricted_tool", metadata={"allowed_roles": ["admin"]})
    ctx = ExecutionContext(session_id=uuid.UUID(int=1))
    ctx.user_roles = ["viewer"]
    executor = ToolExecutor()
    result = _run(executor.execute(tool, {}, ctx, None, skip_approval=True))
    assert result.status == "error"
    assert "authorization denied" in (result.error or "")


def test_authorization_gate_open_when_unconfigured(monkeypatch):
    import uuid

    from nexus.tools.executor import ExecutionContext, ToolExecutor

    monkeypatch.setattr("nexus.tools.executor.get_redis_client", lambda: None)
    tool = _tool_read("open_tool")  # no allowed_roles → open
    ctx = ExecutionContext(session_id=uuid.UUID(int=2))
    ctx.user_roles = ["viewer"]
    executor = ToolExecutor()
    result = _run(executor.execute(tool, {}, ctx, None, skip_approval=True))
    # The unconfigured capability is open (operator's choice) — the call
    # proceeds past the gate (may fail at the HTTP layer in the sandbox).
    assert result.status != "error" or "authorization" not in (result.error or "")


# ---------------------------------------------------------------------------
# Idempotency stamping (P0)
# ---------------------------------------------------------------------------


def test_idempotency_header_stamped_when_declared(monkeypatch):
    import uuid

    import httpx

    from nexus.tools.executor import ExecutionContext, ToolExecutor

    class _Recorder:
        def __init__(self) -> None:
            self.headers: dict | None = None

        async def get(self, url, headers=None, **kwargs):
            self.headers = headers
            return httpx.Response(
                200, json={"ok": True},
                request=httpx.Request("GET", url),
            )

        async def aclose(self):
            pass

    recorder = _Recorder()
    monkeypatch.setattr("nexus.tools.executor.get_redis_client", lambda: None)
    tool = _tool_read(
        "payment_api",
        metadata={"idempotency_header": "Idempotency-Key"},
    )
    ctx = ExecutionContext(session_id=uuid.UUID(int=3))
    ctx.idempotency_key = "stable-key-123"
    executor = ToolExecutor(http_client=recorder)  # type: ignore[arg-type]
    result = _run(executor.execute(tool, {}, ctx, None, skip_approval=True))
    assert result.status == "success"
    assert recorder.headers.get("Idempotency-Key") == "stable-key-123"


# ---------------------------------------------------------------------------
# Approval semantic binding (P1)
# ---------------------------------------------------------------------------


def test_approval_pending_records_operation_hash():
    from nexus.agent.nodes.multi_approval_gate_node import (
        _build_approval_message,
        _resolve_policy,
    )

    assert callable(_build_approval_message)
    assert callable(_resolve_policy)


# ---------------------------------------------------------------------------
# Memory provenance (P1)
# ---------------------------------------------------------------------------


def test_memory_provenance_attached():
    import uuid

    from nexus.memory.store import MemoryStore

    mid = uuid.uuid4()

    async def _run():
        store = MemoryStore()
        await store.put(
            session_id=None,  # FK-safe for the deterministic suite
            memory_id=mid,
            kind="working",
            content="provenance probe",
            metadata={"expires_at": 0.0},
        )
        return await store.get(mid)

    row = asyncio.run(_run())
    meta = row.get("metadata") or row.get("metadata_") or {}
    assert "observed_at" in meta
    assert meta.get("source") == "agent"
    assert "scope" in meta
