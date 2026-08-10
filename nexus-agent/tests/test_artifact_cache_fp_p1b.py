"""P1-B.3 — artifact-cache fingerprint gap.

A cached tool result must never be reused after the capability/endpoint/
schema contract that produced it changes. The artifact-cache keys now
carry the registry fingerprint + tool-schema content hash alongside the
architecture fingerprint, execution key, and session scope.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest


class _Task:
    def __init__(self, tid: str) -> None:
        self.id = tid
        self.tool_name = "t1"
        self.inputs = {"city": "Tokyo"}
        self.max_retries = 0
        self.endpoint_url = "https://api.example.com/op"
        self.http_method = "GET"
        self.candidate_endpoints = []


class _Wave:
    def __init__(self, *tasks) -> None:
        self.tasks = list(tasks)
        self.wave = 0


class _Tool:
    async def execute(self, tool, inputs, context, session, skip_approval=False):
        from nexus.tools.result import ToolResult

        return ToolResult(
            tool_id=uuid.uuid4(), tool_name=tool.name,
            status="success", data={"echo": inputs}, duration_ms=1,
            http_status=200,
        )


class TestArtifactCacheContractFingerprints:
    @pytest.fixture(autouse=True)
    def _no_db(self, monkeypatch):
        import nexus.memory.store as _ms

        class _NoSession:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *a):
                return False

        monkeypatch.setattr("nexus.db.async_session", lambda: _NoSession())

        self._captured = {"reads": [], "writes": []}

        async def _capture_find(*a, **k):
            entry = dict(k)
            # a[0] is the MemoryStore instance (bound-method dispatch)
            if len(a) > 1:
                entry["metadata_filter"] = a[1]
            elif a:
                entry["metadata_filter"] = a[0]
            self._captured["reads"].append(entry)
            return []

        async def _capture_put(*a, **k):
            entry = dict(k)
            if len(a) > 1:
                entry["metadata_filter"] = a[1]
            self._captured["writes"].append(entry)
            return uuid.uuid4()

        monkeypatch.setattr(_ms.MemoryStore, "find_by_metadata", _capture_find)
        monkeypatch.setattr(_ms.MemoryStore, "put", _capture_put)

    def _tool_map(self, schema: dict) -> dict:
        return {
            "t1": {
                "id": str(uuid.uuid4()),
                "description": "d",
                "input_schema": schema,
                "output_schema": {"type": "object", "properties": {}},
                "validation_rules": {},
                "auth_type": "none",
                "auth_ref": "",
                "cacheable": True,
                "idempotent": False,
                "enabled": True,
            }
        }

    def _run(self, schema: dict):
        from nexus.agent.executors.concurrent_executor import ConcurrentExecutor
        from nexus.execution.ledger import CompletedExecutionLedger

        class _Store:
            async def find(self, s, k):
                return None

            async def claim(self, s, k, t, lease_s, fp, agent_run_id=None):
                return True

            async def complete(self, s, k, r, t, agent_run_id=None):
                pass

            async def release(self, s, k, t):
                pass

        ex = ConcurrentExecutor(
            tool_executor=_Tool(),
            tool_map=self._tool_map(schema),
            session_id="s1",
            ledger=CompletedExecutionLedger(store=_Store()),
        )
        t = _Task("a")
        asyncio.run(
            ex.execute(tasks=[t], waves=[_Wave(t)], per_tool_timeout=5, global_timeout=30)
        )

    def test_reads_carry_contract_fingerprints(self):
        self._run({"type": "object", "properties": {"city": {"type": "string"}}})
        assert self._captured["reads"], "the cache read must have happened"
        meta = self._captured["reads"][0]["metadata_filter"]
        assert "reg_fp" in meta, "the registry fingerprint must key the read"
        assert "schema_hash" in meta, "the schema hash must key the read"
        assert "arch_fp" in meta
        assert "execution_key" in meta
        assert self._captured["reads"][0]["session_scope"] == "s1"

    def test_schema_change_changes_the_read_key(self):
        self._run({"type": "object", "properties": {"city": {"type": "string"}}})
        first = dict(self._captured["reads"][0]["metadata_filter"])
        self._captured["reads"].clear()
        self._run({"type": "object", "properties": {"city": {"type": "integer"}}})
        second = dict(self._captured["reads"][0]["metadata_filter"])
        assert first["schema_hash"] != second["schema_hash"], (
            "a tool schema change must change the artifact-cache key — the "
            "old result must never be reused (P1-B.3)"
        )

    def test_writes_carry_the_same_contract_fingerprints(self):
        self._run({"type": "object", "properties": {"city": {"type": "string"}}})
        writes = [w for w in self._captured["writes"]]
        assert writes, "the cache write must have happened"
        meta = writes[0]["metadata"]
        assert "reg_fp" in meta
        assert "schema_hash" in meta

    def test_read_write_keys_agree(self):
        """The read metadata must match the write metadata — mismatched
        keys make the cache dead code."""
        self._run({"type": "object", "properties": {"city": {"type": "string"}}})
        read_meta = self._captured["reads"][0]["metadata_filter"]
        write_meta = self._captured["writes"][0]["metadata"]
        for key in ("reg_fp", "schema_hash", "arch_fp", "execution_key"):
            assert read_meta.get(key) == write_meta.get(key), (
                f"read/write mismatch on '{key}'"
            )

    def test_registry_change_changes_the_read_key(self, monkeypatch):
        """A registry/endpoint contract change (different reg_fp) must
        prevent reuse of an old cached result."""
        import nexus.compiler.cache as _cache

        fps = iter(["reg-v1", "reg-v2"])
        monkeypatch.setattr(
            _cache, "_registry_fingerprint",
            lambda: next(fps),
        )
        self._run({"type": "object", "properties": {"city": {"type": "string"}}})
        first = dict(self._captured["reads"][0]["metadata_filter"])
        self._captured["reads"].clear()
        self._run({"type": "object", "properties": {"city": {"type": "string"}}})
        second = dict(self._captured["reads"][0]["metadata_filter"])
        assert first["reg_fp"] != second["reg_fp"]



