"""D4/P0-D — optimizer safety.

The optimizer must never change execution semantics merely to make the
graph smaller:
- dedup: only idempotent (+ dedup-safe when declared) capabilities
- map identity: includes the iterate_over collection
- parallel fusion: requires endpoint supports_batch metadata
"""

from __future__ import annotations

from nexus.compiler.ir_models import ExecutionGraph, MapNode, ToolNode
from nexus.compiler.passes import pass_deduplication as dedup
from nexus.compiler.passes import pass_parallel_fusion as fusion


def _tool(nid: str, tool_name: str = "send_email", inputs: dict | None = None) -> ToolNode:
    return ToolNode(
        id=nid,
        symbolic_ref=nid,
        capability=tool_name,
        tool_name=tool_name,
        inputs=inputs or {},
        depends_on=[],
    )


def _map(nid: str, tool_name: str, iterate_over: str, inputs: dict | None = None) -> MapNode:
    body = _tool(f"{nid}_body", tool_name, inputs)
    return MapNode(
        id=nid,
        symbolic_ref=f"{nid}_map",
        iterate_over=iterate_over,
        body=body,
        depends_on=[],
    )


def _inject_gc(monkeypatch, idempotent: dict[str, bool] | None = None, supports_batch: dict[str, bool] | None = None):
    """Fake GC with registry contract metadata for the passes."""
    from types import SimpleNamespace as _NS

    import nexus.context.global_context as gc_mod

    class _GC:
        capability_index = {
            name: {"contract": _NS(idempotent=bool(idem), dedup_safe=None)}
            for name, idem in (idempotent or {}).items()
        }
        capability_providers = {
            name: [{"endpoints": [{"supports_batch": bool(sb)}]}]
            for name, sb in (supports_batch or {}).items()
        }

    monkeypatch.setattr(gc_mod, "get_global_context", lambda: _GC())


class TestDedupSafety:
    def test_non_idempotent_ops_never_merged(self, monkeypatch):
        _inject_gc(monkeypatch, idempotent={"send_email": False})
        graph = ExecutionGraph(
            graph_id="g",
            nodes={
                "a": _tool("a", "send_email", {"to": "x"}),
                "b": _tool("b", "send_email", {"to": "x"}),
            },
            waves=[["a", "b"]],
        )
        result = dedup.run(graph)
        assert len(result.nodes) == 2, (
            "two identical side-effecting calls are TWO distinct operations"
        )

    def test_idempotent_ops_may_merge(self, monkeypatch):
        _inject_gc(monkeypatch, idempotent={"get_weather": True})
        graph = ExecutionGraph(
            graph_id="g",
            nodes={
                "a": _tool("a", "get_weather", {"city": "Tokyo"}),
                "b": _tool("b", "get_weather", {"city": "Tokyo"}),
            },
            waves=[["a", "b"]],
        )
        result = dedup.run(graph)
        assert len(result.nodes) == 1

    def test_absent_metadata_never_merges(self, monkeypatch):
        _inject_gc(monkeypatch, idempotent={})
        graph = ExecutionGraph(
            graph_id="g",
            nodes={
                "a": _tool("a", "unknown_tool", {"k": 1}),
                "b": _tool("b", "unknown_tool", {"k": 1}),
            },
            waves=[["a", "b"]],
        )
        result = dedup.run(graph)
        assert len(result.nodes) == 2, "no metadata = no dedup (safe default)"

    def test_maps_over_different_collections_never_merged(self, monkeypatch):
        _inject_gc(monkeypatch, idempotent={"get_weather": True})
        graph = ExecutionGraph(
            graph_id="g",
            nodes={
                "m1": _map("m1", "get_weather", "cities_a"),
                "m2": _map("m2", "get_weather", "cities_b"),
            },
            waves=[["m1", "m2"]],
        )
        result = dedup.run(graph)
        assert len(result.nodes) == 2, (
            "identical map bodies over different collections are distinct"
        )

    def test_maps_over_same_collection_may_merge(self, monkeypatch):
        _inject_gc(monkeypatch, idempotent={"get_weather": True})
        graph = ExecutionGraph(
            graph_id="g",
            nodes={
                "m1": _map("m1", "get_weather", "cities"),
                "m2": _map("m2", "get_weather", "cities"),
            },
            waves=[["m1", "m2"]],
        )
        result = dedup.run(graph)
        assert len(result.nodes) == 1


class TestFusionSafety:
    @staticmethod
    def _six_map_graph() -> ExecutionGraph:
        return ExecutionGraph(
            graph_id="g",
            nodes={
                f"m{i}": _map(f"m{i}", "get_weather", "cities")
                for i in range(6)
            },
            waves=[["m0", "m1", "m2", "m3", "m4", "m5"]],
        )

    def test_fusion_requires_supports_batch(self, monkeypatch):
        _inject_gc(monkeypatch, supports_batch={"get_weather": False})
        result = fusion.run(self._six_map_graph())
        assert len(result.nodes) == 6, (
            "without supports_batch metadata the maps must NOT be fused"
        )

    def test_fusion_with_supports_batch(self, monkeypatch):
        _inject_gc(monkeypatch, supports_batch={"get_weather": True})
        result = fusion.run(self._six_map_graph())
        assert len(result.nodes) == 1, "declared batch endpoints may fuse"

    def test_fusion_absent_metadata_safe_default(self, monkeypatch):
        _inject_gc(monkeypatch, supports_batch={})
        result = fusion.run(self._six_map_graph())
        assert len(result.nodes) == 6
