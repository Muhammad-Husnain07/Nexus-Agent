"""ResolutionEngine — the single source of truth for capability/workflow relevance.

One pipeline answers "what is relevant?" for every consumer:

- **Router** consumes binary facts (``has_*_candidates``) — never scores,
  never confidence bands, never thresholds.
- **Planner** consumes ranked candidates with scores, confidence, match
  sources, and availability facts.
- **Telemetry / debug** consumes the typed ``ResolutionResult`` (including the
  human-readable ``explanation``).

Purity (runtime contract §1): the engine performs NO DB writes, NO Redis
mutations, NO embedding generation, NO HTTP calls. All inputs (GlobalContext
indexes, template matcher) are injected as readers.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from nexus.capabilities.resolution_result import (
    Availability,
    CapabilityCandidate,
    ResolutionMetadata,
    ResolutionResult,
    WorkflowCandidate,
)

logger = structlog.get_logger("nexus.capabilities.resolution_engine")

# Immutable implementation version (module constant — never settings/env).
RESOLVER_VERSION = 1


class ConfidenceClassifier:
    """Maps raw match signals to a coarse confidence band.

    Phase 1: score bands only (documented, single source). Roadmap Phase 6
    extends ``classify`` with multi-factor signals (embedding similarity,
    schema compatibility, alias strength) behind the SAME method — no API
    change for consumers.
    """

    HIGH_FROM = 0.90
    MEDIUM_FROM = 0.70

    def classify(self, score: float, factors: dict[str, Any] | None = None) -> str:
        """Return ``high`` | ``medium`` | ``low`` for a match score.

        Bands are labels for humans and coarse routing hints — they are never
        used as numeric thresholds by the router.
        """
        if score >= self.HIGH_FROM:
            return "high"
        if score >= self.MEDIUM_FROM:
            return "medium"
        return "low"


def registry_version() -> int:
    """Current registry version (incrementing, from the persisted marker).

    Distinct from the content-hash fingerprint. Synchronous best-effort;
    0 when unavailable."""
    try:
        from nexus.tools.registry import get_tool_registry_marker

        marker = get_tool_registry_marker()
        if marker.startswith("tools:"):
            return int(marker.split(":", 1)[1]) % 1_000_000_000
    except Exception:
        pass
    return 0




class ResolutionEngine:
    """Resolves capabilities and workflow templates for a query."""

    def __init__(self, top_k: int | None = None) -> None:
        self.top_k = top_k or 15
        self.confidence = ConfidenceClassifier()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def resolve(
        self,
        query: str,
        domain_hint: str | None = None,
        top_k: int | None = None,
        gc: Any | None = None,
    ) -> ResolutionResult:
        """Resolve ``query`` into ranked capability + workflow candidates.

        Args:
            query: The user request / planning intent.
            domain_hint: Optional deterministic domain to narrow to first.
            top_k: Max capability candidates (defaults to engine top_k).
            gc: GlobalContext to read indexes from (injectable for tests).

        Returns:
            An immutable ``ResolutionResult``.
        """
        started = time.perf_counter()
        layers: list[str] = []

        if gc is None:
            from nexus.context.global_context import get_global_context

            gc = get_global_context()
        cap_meta_all: dict[str, dict[str, Any]] = getattr(gc, "capability_index", {}) or {}

        # --- Capability stream -------------------------------------------------
        retrieved = self._retrieve_capabilities(query, top_k=top_k, gc=gc)
        layers.extend(r.matched_by for r in retrieved if r.matched_by not in layers)
        if not retrieved:
            layers.append("bm25")

        # D10 EMBEDDING A/B (flag-gated, isolated): nv-embed-v1 semantic
        # retrieval over the registered tool embeddings (pgvector cosine)
        # adds candidates to the pool. DETERMINISTIC semantics still decide
        # — embeddings only retrieve. The flag keeps this experiment fully
        # switchable without touching any frozen contract.
        try:
            from nexus.config.settings import get_settings as _emb_settings

            if bool(getattr(_emb_settings().resolver, "enable_embedding_retrieval", False)):
                _emb_hits = await self._embedding_retrieve(query, top_k=top_k or self.top_k)
                if _emb_hits:
                    _existing = {r.name for r in retrieved}
                    retrieved = list(retrieved) + [h for h in _emb_hits if h.name not in _existing]
                    layers.append("embedding")
                    logger.info(
                        "resolution_engine.embedding_retrieval",
                        added=len(retrieved) - len([r for r in retrieved if r.name in _existing]),
                        query=query[:50],
                    )
        except Exception as _emb_exc:
            logger.debug("resolution_engine.embedding_retrieval_failed", error=str(_emb_exc)[:150])

        candidates = self._to_candidates(retrieved, cap_meta_all, gc)

        # Domain narrowing (metadata-driven: domain_index from registry).
        if domain_hint:
            layers.append("domain")
            domain_ops = set((getattr(gc, "domain_index", {}) or {}).get(domain_hint, []))
            if domain_ops:
                candidates = tuple(c for c in candidates if c.name in domain_ops)

        # Availability facts (binary, deterministic).
        candidates = tuple(self._with_availability(c, gc) for c in candidates)
        available = tuple(c for c in candidates if c.availability == "available")

        # --- Workflow stream ---------------------------------------------------
        workflow_candidates = await self._match_workflows(query)
        if workflow_candidates:
            layers.append("workflow")

        # --- Metadata + explanation -------------------------------------------
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        metadata = ResolutionMetadata(
            elapsed_ms=elapsed_ms,
            catalog_size=len(cap_meta_all),
            fingerprint=self._fingerprint(gc),
            registry_version=registry_version(),
            layers_run=tuple(layers),
            resolver_version=RESOLVER_VERSION,
        )
        explanation = self._build_explanation(query, available, workflow_candidates, candidates)

        return ResolutionResult(
            query=query.strip(),
            domain_hint=domain_hint,
            workflow_candidates=tuple(workflow_candidates),
            capability_candidates=available[: (top_k or self.top_k)],
            has_capability_candidates=bool(available),
            has_workflow_candidates=bool(workflow_candidates),
            metadata=metadata,
            explanation=explanation,
        )

    # ------------------------------------------------------------------
    # Capability stream internals
    # ------------------------------------------------------------------

    def _retrieve_capabilities(
        self, query: str, top_k: int | None, gc: Any
    ) -> list[Any]:
        """Run the retriever (alias → boost → BM25). Injectable for tests."""
        try:
            from nexus.capabilities.retrieval import get_capability_retriever

            retriever = get_capability_retriever()
            return retriever.retrieve(query, top_k=top_k or self.top_k, gc=gc)
        except Exception as exc:
            logger.warning("resolution_engine.retrieval_failed", error=str(exc)[:200])
            return []

    async def _embedding_retrieve(
        self, query: str, top_k: int
    ) -> list[Any]:
        """D10: nv-embed-v1 semantic retrieval (pgvector cosine distance).

        Queries the registered tool embeddings (metadata-driven: the
        registry generates embeddings from the tool's description/purpose/
        aliases/keywords) and maps hits onto the retriever's
        ``RetrievedCapability`` shape. Embeddings RETRIEVE; the
        deterministic ranker and CapabilitySemantics decide.
        """
        try:
            from nexus.capabilities.retrieval import RetrievedCapability  # noqa: PLC0415
            from nexus.db.base import async_session as _emb_db  # noqa: PLC0415
            from nexus.llm.client import LLMClient  # noqa: PLC0415
            from nexus.tools.registry import ToolRegistry  # noqa: PLC0415

            async with _emb_db() as _s:
                reg = ToolRegistry(LLMClient())
                hits = await reg.search_semantic(_s, query, k=max(4, top_k))
            out: list[Any] = []
            for h in hits:
                tool = getattr(h, "tool", None)
                name = getattr(tool, "name", "") or getattr(tool, "logical_op_name", "")
                if not name:
                    continue
                score = float(getattr(h, "score", 0.0) or 0.0)
                if score <= 0:
                    continue
                out.append(RetrievedCapability(
                    name=str(name),
                    domain=str(getattr(tool, "category", "") or ""),
                    score=round(score, 4),
                    matched_by="embedding",
                    reasons=("embedding",),
                ))
            return out
        except Exception as exc:
            logger.debug("resolution_engine.embedding_retrieve_failed", error=str(exc)[:150])
            return []

    def _to_candidates(
        self,
        retrieved: list[Any],
        cap_meta_all: dict[str, dict[str, Any]],
        gc: Any,
    ) -> tuple[CapabilityCandidate, ...]:
        """Map retrieved hits to typed candidates (stable IDs, reasons)."""
        out: list[CapabilityCandidate] = []
        for hit in retrieved:
            name = hit.name
            meta = cap_meta_all.get(name) or {}
            out.append(CapabilityCandidate(
                id=str(meta.get("id") or name),
                name=name,
                domain=str(meta.get("domain") or hit.domain or ""),
                score=round(float(hit.score), 3),
                confidence=self.confidence.classify(float(hit.score)),
                match_sources=tuple(hit.reasons or (hit.matched_by,)),
                reasons=tuple(hit.reasons or (hit.matched_by,)),
            ))
        return tuple(out)

    def _with_availability(
        self, candidate: CapabilityCandidate, gc: Any
    ) -> CapabilityCandidate:
        """Attach the availability fact for a candidate.

        Deterministic and metadata-driven:
        - ``disabled`` — excluded from indexes entirely (with_tool_metadata),
          so candidates reaching this point are not disabled.
        - ``unavailable`` — provider circuit breaker open.
        - ``rate_limited`` — reserved for Phase 4 policy headroom.
        """
        availability: Availability = "available"
        reason: str | None = None
        try:
            from nexus.tools.circuit_breaker import breaker_state

            state = breaker_state(candidate.name)
            if state in ("open", "half_open"):
                availability = "unavailable"
                reason = f"circuit breaker {state}"
        except Exception:
            pass
        if availability == "available":
            # Endpoint-existence fact (metadata-driven): a capability with NO
            # registered provider or no endpoint URL cannot be executed —
            # it must never reach the planner's catalog (plans never include
            # unavailable capabilities). This is what keeps compiled-graph
            # stubs (e.g. an unconfigured web_search) out of planning.
            providers = (gc.capability_providers or {}).get(candidate.name) or []
            has_endpoint = any(
                isinstance(p, dict) and bool(p.get("url"))
                for p in providers
            )
            if not has_endpoint:
                availability = "unavailable"
                reason = "no executable endpoint registered"
        if candidate.availability != "available":
            return candidate
        if availability == "available":
            return candidate
        return CapabilityCandidate(
            id=candidate.id,
            name=candidate.name,
            domain=candidate.domain,
            score=candidate.score,
            confidence=candidate.confidence,
            match_sources=candidate.match_sources,
            reasons=candidate.reasons,
            availability=availability,
            availability_reason=reason,
        )

    # ------------------------------------------------------------------
    # Workflow stream internals
    # ------------------------------------------------------------------

    async def _match_workflows(self, query: str) -> tuple[WorkflowCandidate, ...]:
        """Match workflow templates (metadata-driven; single matcher impl)."""
        try:
            from nexus.capabilities.template_engine import match_template_candidates

            matched = await match_template_candidates(query, limit=3)
        except Exception as exc:
            logger.warning("resolution_engine.workflow_match_failed", error=str(exc)[:200])
            return ()
        out: list[WorkflowCandidate] = []
        for m in matched:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name") or "")
            if not name:
                continue
            score = float(m.get("score") or 0.0)
            tags = tuple(str(t) for t in (m.get("tags") or []))
            out.append(WorkflowCandidate(
                id=str(m.get("id") or name),
                name=name,
                executable_type="workflow",
                score=round(score, 3),
                confidence=self.confidence.classify(score),
                match_sources=("fuzzy",) + (("metadata",) if tags else ()),
                reasons=(
                    f"template match ({m.get('match_type', 'fuzzy')})",
                    *(f"tag:{t}" for t in tags[:3]),
                ),
                tags=tags,
            ))
        return tuple(out)

    # ------------------------------------------------------------------
    # Shared internals
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(gc: Any) -> str:
        try:
            checksum = getattr(gc, "registry_checksum", "") or ""
            from nexus.tools.registry import get_tool_registry_marker

            marker = get_tool_registry_marker()
            return f"{str(checksum)[:16]}|{marker}"[:64]
        except Exception:
            return ""

    @staticmethod
    def _build_explanation(
        query: str,
        available: tuple[CapabilityCandidate, ...],
        workflows: tuple[WorkflowCandidate, ...],
        all_candidates: tuple[CapabilityCandidate, ...],
    ) -> str:
        """Human-readable 'why' narrative — debug/telemetry only."""
        lines: list[str] = [f"Query: {query.strip()[:80]}"]
        excluded = [
            c for c in all_candidates
            if c.availability != "available" and c.name not in {a.name for a in available}
        ]
        for c in available[:5]:
            lines.append(
                f"  {c.name} — score {c.score:.2f} ({c.confidence}) via {', '.join(c.match_sources)}"
            )
        if workflows:
            lines.append("  workflow templates: " + ", ".join(w.name for w in workflows[:3]))
        if excluded:
            lines.append("  excluded (unavailable): " + ", ".join(
                f"{c.name} ({c.availability_reason or c.availability})" for c in excluded[:3]
            ))
        return "\n".join(lines)


_engine: ResolutionEngine | None = None


def get_resolution_engine() -> ResolutionEngine:
    """Return the singleton ResolutionEngine (stateless — safe to share)."""
    global _engine
    if _engine is None:
        _engine = ResolutionEngine()
    return _engine
