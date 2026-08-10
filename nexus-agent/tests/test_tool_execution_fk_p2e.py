"""P2-E tool_execution FK REPAIR gate.

The canonical ``tool_execution.tool_id`` identity is the REGISTRY tool id.
Compiled-graph/synthetic identities (the zero-UUID stub used when a tool
has no registry row) must NEVER be written as a database tool foreign key —
an unregistered tool must produce NO execution row rather than a silently
lost row via FK violation.

Under test:

1. The registry-tool metadata builder produces a ToolRead-valid dict
   carrying the REGISTRY id (canonical identity) — including the
   ToolRead-required fields (version/created_at/updated_at) that were
   previously omitted (causing validation fallback to the stub for
   REGISTERED tools like get_exchange_rates).
2. Persistence with a registry id writes the row with tool_id == registry id.
3. Persistence with the zero-UUID stub id writes NOTHING (typed warning,
   never a crash, never a synthetic FK).
4. The zero-UUID constant is shared between the stub and the guard.
"""

from __future__ import annotations

import asyncio
import uuid

from nexus.tools.executor import _ZERO_UUID


class _RegistryTool:
    """Shape-compatible with the SQLAlchemy registry Tool row."""

    def __init__(self, name: str, tool_id: uuid.UUID | None = None):
        self.name = name
        self.id = tool_id or uuid.uuid4()
        self.description = "d"
        self.purpose = "p"
        self.endpoint_url = "https://example.com/x"
        self.http_method = "GET"
        self.auth_type = "none"
        self.auth_ref = ""
        self.input_schema = {"type": "object", "properties": {}}
        self.output_schema = {"type": "object", "properties": {}}
        self.validation_rules = {}
        self.examples = []
        self.tags = []
        self.category = "general"
        self.risk_level = "low"
        self.requires_approval = False
        self.enabled = True
        self.rate_limit_per_minute = None
        self.keywords = None
        self.aliases = None
        self.idempotent = False
        self.cacheable = True
        self.mcp_server_url = None
        self.version = 3


# ---------------------------------------------------------------------------
# 1. canonical registry metadata builder
# ---------------------------------------------------------------------------


def test_meta_dict_carries_registry_id_and_validates():
    from nexus.agent.graph import _tool_meta_to_read_dict
    from nexus.tools.schemas import ToolRead

    registry_id = uuid.uuid4()
    meta = _tool_meta_to_read_dict(_RegistryTool("t1", registry_id))
    assert meta["id"] == str(registry_id)
    read = ToolRead.model_validate(meta)
    assert read.id == registry_id
    assert read.version == 3


def test_meta_dict_version_defaults_when_missing():
    from nexus.agent.graph import _tool_meta_to_read_dict
    from nexus.tools.schemas import ToolRead

    t = _RegistryTool("t2")
    t.version = None
    meta = _tool_meta_to_read_dict(t)
    assert meta["version"] == 1
    assert ToolRead.model_validate(meta).version == 1


# ---------------------------------------------------------------------------
# 2. persistence with a registry id writes the row
# ---------------------------------------------------------------------------


def test_persist_writes_registry_id_row():
    from nexus.tools.executor import ExecutionContext, ToolExecutor

    added = []

    class _FakeSession:
        def add(self, obj):
            added.append(obj)

        async def flush(self):
            pass

        async def commit(self):
            pass

    registry_id = uuid.uuid4()
    tool = _RegistryTool("t3", registry_id)
    result = type(
        "ToolResult",
        (),
        {"data": {"x": 1}, "status": "success", "http_status": 200,
         "duration_ms": 5, "error": None, "retried": False},
    )()
    ctx = ExecutionContext(
        session_id=uuid.uuid4(), agent_run_id="run-1", execution_key="ek-1"
    )
    asyncio.run(
        ToolExecutor._persist_execution(_FakeSession(), tool, ctx, result, {})
    )
    assert len(added) == 1
    assert added[0].tool_id == registry_id
    assert added[0].agent_run_id == "run-1"
    assert added[0].execution_key == "ek-1"


# ---------------------------------------------------------------------------
# 3. zero-UUID stub identity never enters the FK
# ---------------------------------------------------------------------------


def test_persist_skips_zero_uuid_stub():
    from nexus.tools.executor import ExecutionContext, ToolExecutor

    added = []

    class _FakeSession:
        def add(self, obj):
            added.append(obj)

        async def flush(self):
            pass

        async def commit(self):
            pass

    tool = _RegistryTool("stub_tool")
    tool.id = uuid.UUID(_ZERO_UUID)
    result = type(
        "ToolResult",
        (),
        {"data": {}, "status": "success", "http_status": 200,
         "duration_ms": 1, "error": None, "retried": False},
    )()
    ctx = ExecutionContext(session_id=uuid.uuid4(), agent_run_id="run-2")
    asyncio.run(
        ToolExecutor._persist_execution(_FakeSession(), tool, ctx, result, {})
    )
    assert added == [], "a synthetic (zero-UUID) tool id must never be persisted"


def test_zero_uuid_constant_shared_with_stub():
    """The stub in the executor and the persist guard must agree on the
    synthetic identity — a drift would re-open the FK hole."""
    from nexus.agent.executors.concurrent_executor import _ZERO_UUID as _exec_zero

    assert _exec_zero == _ZERO_UUID


# ---------------------------------------------------------------------------
# 4. invariant: registry identity is the only persisted tool id
# ---------------------------------------------------------------------------


def test_chain_registry_id_flow():
    """ToolRead built from the registry dict carries the registry id — the
    id that reaches tool_execution.tool_id is the registry identity."""
    from nexus.agent.graph import _tool_meta_to_read_dict
    from nexus.tools.schemas import ToolRead

    registry_id = uuid.uuid4()
    read = ToolRead.model_validate(_tool_meta_to_read_dict(_RegistryTool("t4", registry_id)))
    assert str(read.id) == str(registry_id)
    # a compiled-graph synthetic id can never pass through this builder
    assert _ZERO_UUID not in _tool_meta_to_read_dict(_RegistryTool("t5", registry_id)).values()
