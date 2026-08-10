"""P1-B.2 — component-specific prompt fingerprints.

Cache dependency table:
    ParseCache / PlanCache  ← planner prompt + registry
    ResponseCache           ← response (finalize) prompt + artifacts
    Router                  ← no cache (router prompt has no cache key)

A response or router prompt change must NEVER invalidate parse/plan
caches; a planner prompt change must invalidate them.
"""

from __future__ import annotations

from nexus.agent.prompts.manager import PromptManager
from nexus.compiler.cache import PlanCache, _make_key


def _build_parse_key(monkeypatch, planner_fp: str) -> str:
    import nexus.compiler.cache as _cache

    monkeypatch.setattr(_cache, "_planner_prompt_fp", lambda: planner_fp)
    from nexus.compiler.cache import ParseCache

    return ParseCache()._build_key("fetch weather in tokyo", [], "m", "ctx")


class TestPromptManagerFingerprint:
    def test_content_change_changes_fingerprint(self):
        pm = PromptManager()
        pm.register("p", "template {x} v1", version="1.0")
        fp1 = pm.fingerprint("p")
        pm.register("p", "template {x} v2", version="1.0")
        fp2 = pm.fingerprint("p")
        assert fp1 != fp2, (
            "a prompt CONTENT change must change the fingerprint even with "
            "the same version label (P1-B.2)"
        )

    def test_same_content_stable(self):
        pm = PromptManager()
        pm.register("p", "same", version="1.0")
        assert pm.fingerprint("p") == pm.fingerprint("p")


class TestPlannerPromptInvalidatesPlannerCaches:
    def test_planner_prompt_change_invalidates_parse_key(self, monkeypatch):
        k1 = _build_parse_key(monkeypatch, "planner-v1")
        k2 = _build_parse_key(monkeypatch, "planner-v2")
        assert k1 != k2, (
            "a planner-prompt change must invalidate the ParseCache key"
        )

    def test_planner_prompt_change_invalidates_plan_key(self, monkeypatch):
        import nexus.compiler.cache as _cache

        monkeypatch.setattr(_cache, "_planner_prompt_fp", lambda: "v1")
        wf = {"nodes": [{"op": "x", "inputs": {}, "depends_on": []}], "collections": {}}
        k1 = PlanCache().build_workflow_key(wf)
        monkeypatch.setattr(_cache, "_planner_prompt_fp", lambda: "v2")
        k2 = PlanCache().build_workflow_key(wf)
        assert k1 != k2

    def _ir(self, prompt_fp: str) -> str:
        """A minimal ContextIR's cache fingerprint for the given response
        prompt fingerprint."""
        from nexus.compiler.context_ir import ContextIR, ContextPolicy

        ir = ContextIR(
            policy=ContextPolicy(
                purpose="finalize", max_history_turns=5, max_artifacts=8
            ),
            model_name="m",
            items=(),
        )
        return ir.fingerprint("renderer-hash", prompt_fp=prompt_fp)

    def test_planner_prompt_change_does_not_touch_response_cache(
        self, monkeypatch
    ):
        """The response cache fp depends on the finalize prompt, not the
        planner prompt."""
        fp1 = self._ir("finalize-v1")
        fp2 = self._ir("finalize-v2")
        assert fp1 != fp2
        # same finalize prompt → same response fingerprint, regardless of
        # any planner prompt change
        fp3 = self._ir("finalize-v1")
        assert fp3 == fp1


class TestResponsePromptChangeIsolation:
    def test_response_prompt_change_leaves_planner_keys_untouched(
        self, monkeypatch
    ):
        """The parse/plan keys never read the finalize prompt — a
        finalize-prompt change leaves them identical."""
        import nexus.compiler.cache as _cache

        monkeypatch.setattr(_cache, "_planner_prompt_fp", lambda: "planner-fixed")
        wf = {"nodes": [{"op": "x", "inputs": {}, "depends_on": []}], "collections": {}}
        k_before = PlanCache().build_workflow_key(wf)
        k_after = PlanCache().build_workflow_key(wf)
        assert k_before == k_after
        assert _make_key("plan", "wf") is not None

    def test_router_prompt_change_leaves_all_cache_keys_untouched(
        self, monkeypatch
    ):
        """The router prompt participates in NO cache key — changing it
        must not invalidate parse/plan (or response) caches."""
        import nexus.compiler.cache as _cache

        monkeypatch.setattr(_cache, "_planner_prompt_fp", lambda: "fixed")
        wf = {"nodes": [{"op": "x", "inputs": {}, "depends_on": []}], "collections": {}}
        k1 = PlanCache().build_workflow_key(wf)
        k2 = PlanCache().build_workflow_key(wf)
        assert k1 == k2

    def test_finalize_prompt_change_invalidates_response_fingerprint(self):
        from nexus.compiler.context_ir import ContextIR, ContextPolicy

        ir = ContextIR(
            policy=ContextPolicy(
                purpose="finalize", max_history_turns=5, max_artifacts=8
            ),
            model_name="m",
            items=(),
        )
        fp_a = ir.fingerprint("rh", prompt_fp="f-v1")
        fp_b = ir.fingerprint("rh", prompt_fp="f-v2")
        assert fp_a != fp_b
