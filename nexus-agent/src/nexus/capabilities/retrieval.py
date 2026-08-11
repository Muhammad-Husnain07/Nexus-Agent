"""Capability Retriever — narrows the catalog BEFORE the LLM planner.

Retrieval answers "which capabilities should the planner consider?" — it is
distinct from resolution (which answers "the planner chose X; which
registered capability is that?").

Design (metadata-driven, no hardcoded names):

- A per-capability **document** is built from registry metadata: name,
  logical op, aliases, category/domain, keywords, produces, consumes,
  description, purpose.
- **Keyword / alias / domain prefilters** run first (O(1) against
  GlobalContext indexes).
- **BM25 ranking** scores the surviving candidates against the query.
- Top-K results are returned for the planner's constrained Literal + prompt.

Embeddings are deliberately NOT used at retrieval time: BM25 + aliases is
sufficient at hundreds of capabilities and the index shape leaves room to
swap in pgvector similarity later without touching callers.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.capabilities.retrieval")


@dataclass(frozen=True)
class RetrievedCapability:
    """A retrieval hit for the planner.

    Attributes:
        name: Canonical capability name (logical_op_name).
        domain: Category/domain the capability belongs to.
        aliases: Explicit operator-declared aliases.
        score: Retrieval score (BM25 or prefilter weight).
        matched_by: Primary signal that matched (keyword | alias | domain | bm25).
        reasons: All layers that matched, in order (multi-source truth).
    """

    name: str
    domain: str = ""
    aliases: tuple[str, ...] = ()
    score: float = 0.0
    matched_by: str = "bm25"
    reasons: tuple[str, ...] = ()


@dataclass
class _CapabilityDoc:
    """Searchable document for one capability."""

    name: str
    text: str
    tokens: list[str] = field(default_factory=list)


_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenization for BM25 corpus construction."""
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) > 1]


class CapabilityRetriever:
    """Retrieval engine over the capability catalog.

    The corpus is built from GlobalContext metadata (which itself is built
    from the DB registry at startup). ``retrieve()`` returns the top-K
    candidates for a query — the planner never sees the full catalog.
    """

    def __init__(self, top_k: int | None = None) -> None:
        try:
            settings = get_settings()
            self.top_k = top_k or settings.resolver.top_k_candidates * 5  # 15 default
        except Exception:
            self.top_k = 15
        self._docs: list[_CapabilityDoc] = []
        self._bm25: Any = None
        self._ready = False
        self._cache: dict[str, list[RetrievedCapability]] = {}

    # ------------------------------------------------------------------
    # Corpus build (from GlobalContext — metadata-driven)
    # ------------------------------------------------------------------

    def build_corpus(self, gc: Any) -> None:
        """Build the BM25 corpus from GlobalContext metadata.

        Uses the PREBUILT normalized search document per capability
        (assembled once in ``GlobalContext.with_tool_metadata``) — no
        dynamic assembly per request.

        Args:
            gc: The GlobalContext singleton (providers, keyword, alias,
                domain, capability indexes).
        """
        docs: list[_CapabilityDoc] = []
        capability_index: dict[str, dict[str, Any]] = getattr(gc, "capability_index", {}) or {}

        for name, meta in capability_index.items():
            search_doc = meta.get("search_doc")
            if not search_doc:
                # Fallback assembly (older cached GlobalContexts).
                parts = [
                    name,
                    str(meta.get("logical_op_name") or ""),
                    str(meta.get("domain") or ""),
                    *[str(a) for a in (meta.get("aliases") or [])],
                    *[str(c) for c in (meta.get("capabilities") or [])],
                    *[str(p) for p in (meta.get("produces") or [])],
                    *[str(c) for c in (meta.get("consumes") or [])],
                    *[str(r) for r in (meta.get("related") or [])],
                    *self._capability_keywords(gc, name),
                ]
                search_doc = " ".join(parts)
            doc = _CapabilityDoc(name=name, text=search_doc, tokens=_tokenize(search_doc))
            if doc.tokens:
                docs.append(doc)

        # Fallback: capability_providers keys when capability_index is empty.
        if not docs:
            for name in (getattr(gc, "capability_providers", {}) or {}).keys():
                doc = _CapabilityDoc(name=name, text=name, tokens=_tokenize(name))
                if doc.tokens:
                    docs.append(doc)

        self._docs = docs
        try:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi([d.tokens for d in docs]) if docs else None
        except Exception as exc:
            logger.warning("retriever.bm25_unavailable", error=str(exc)[:200])
            self._bm25 = None
        self._ready = True
        logger.info(
            "retriever.corpus_ready",
            docs=len(docs),
            top_k=self.top_k,
        )

    def _capability_keywords(self, gc: Any, name: str) -> list[str]:
        """Collect keyword-map tokens that point at this capability."""
        kw_map: dict[str, list[str]] = getattr(gc, "capability_keywords", {}) or {}
        hits: list[str] = []
        for kw, caps in kw_map.items():
            if name in caps:
                hits.append(kw)
        return hits

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        gc: Any | None = None,
    ) -> list[RetrievedCapability]:
        """Return the top-K capabilities for ``query``.

        Pipeline: alias exact → domain/keyword prefilter → BM25 rank.
        Returns an empty list when nothing matches — the caller falls back
        to the full catalog or templates.

        Args:
            query: The user request / planning intent.
            top_k: Max results (defaults to configured value).
            gc: GlobalContext to read indexes from (defaults to singleton;
                injectable for tests).

        Returns:
            Ranked list of ``RetrievedCapability``.
        """
        if not self._ready:
            return []
        if not query or not query.strip():
            return []
        q = query.strip().lower()
        key = hashlib.sha256(q.encode()).hexdigest()[:16]
        if key in self._cache:
            return self._cache[key]

        started = time.perf_counter()
        limit = top_k or self.top_k
        results: list[RetrievedCapability] = []

        # 1. Alias exact — strongest signal (explicit operator aliases).
        if gc is None:
            from nexus.context.global_context import get_global_context

            gc = get_global_context()
        alias_index: dict[str, str] = getattr(gc, "alias_index", {}) or {}
        direct = alias_index.get(q) or alias_index.get(q.replace(" ", "_"))
        if direct is None:
            # Alias token-containment: every token of the alias appears in
            # the query (e.g. alias "pikachu info" inside
            # "tell me about pikachu info"). Stronger than BM25.
            q_tokens = set(_tokenize(q))
            best_alias: str | None = None
            best_score = 0
            for alias, cap in alias_index.items():
                alias_tokens = set(_tokenize(alias))
                if not alias_tokens:
                    continue
                if alias_tokens <= q_tokens and len(alias_tokens) > best_score:
                    best_alias = cap
                    best_score = len(alias_tokens)
            direct = best_alias
        if direct:
            results.append(RetrievedCapability(
                name=direct,
                domain=str((getattr(gc, "capability_index", {}) or {}).get(direct, {}).get("domain", "")),
                aliases=tuple((getattr(gc, "capability_index", {}) or {}).get(direct, {}).get("aliases", [])),
                score=100.0,
                matched_by="alias",
                reasons=("exact_alias",),
            ))
            # ALIAS MULTI-MATCH (BENCHMARK FIX): a query may carry MULTIPLE
            # operator-declared aliases ("reverse geocode" AND "current
            # weather" in one request). The single-winner selection above
            # dropped every alias except the longest, so the resolution
            # candidates structurally excluded the other intents' tools —
            # the F8-class planner restriction for multi-intent queries.
            # ALL alias hits are returned (most-specific first), ranked —
            # the same philosophy as the keyword step below.
            q_tokens = set(_tokenize(q))
            alias_hits: list[tuple[int, str]] = []
            for alias, cap in alias_index.items():
                alias_tokens = set(_tokenize(alias))
                if not alias_tokens or cap == direct:
                    continue
                if alias_tokens <= q_tokens:
                    alias_hits.append((len(alias_tokens), cap))
            alias_hits.sort(key=lambda m: -m[0])
            for _n_tokens, cap in alias_hits:
                if any(r.name == cap for r in results):
                    continue
                results.append(RetrievedCapability(
                    name=cap,
                    domain=str((getattr(gc, "capability_index", {}) or {}).get(cap, {}).get("domain", "")),
                    aliases=tuple((getattr(gc, "capability_index", {}) or {}).get(cap, {}).get("aliases", [])),
                    score=100.0,
                    matched_by="alias",
                    reasons=("exact_alias",),
                ))
    # 1b. Example/keyword boost: when the query (token-containment)
    # matches a capability's own examples or keywords, that capability
    # wins — the operator explicitly declared these phrases as
    # triggers. Metadata-driven, stronger than BM25. EVERY matching
    # capability is returned (ranked), not just a single winner —
    # picking one arbitrarily would hide the others from the planner.
    # P0-A FIX: this step runs ALWAYS — an alias hit (e.g. the generic
    # web-search alias "search") must not short-circuit the keyword/
    # example signal for specialized capabilities ("meal", "recipes").
    # The alias step's 100.0 score wins the ranking; the boost keeps
    # the specialized candidates in the pool so the deterministic
    # ranker (specificity + generic suppression) can decide.
        cap_meta_all: dict[str, dict[str, Any]] = getattr(gc, "capability_index", {}) or {}
        q_tokens = set(_tokenize(q))
        if q_tokens:
            # Generic-word demotion: a keyword token that belongs to many
            # capabilities ("the", "use", "and" — prose words) is not
            # discriminative and must not boost. A token is generic when
            # it appears as a keyword token for MORE THAN THREE
            # capabilities (a signal that fires for many capabilities is
            # no signal at all; tokens shared by just two tools, e.g.
            # ``latitude`` for geocode+weather, stay discriminative —
            # metadata-driven, no pattern lists).
            total_caps = max(1, len(cap_meta_all))
            tok_freq: dict[str, int] = {}
            for _meta in cap_meta_all.values():
                for _kw in (_meta.get("keywords") or []):
                    _tokens = _tokenize(str(_kw))
                    if _tokens:
                        tok_freq[_tokens[0]] = tok_freq.get(_tokens[0], 0) + 1
            generic = {
                t for t, count in tok_freq.items()
                if count > 3
            }
            boosted: list[tuple[str, float]] = []
            for cap_name, meta in cap_meta_all.items():
                ex_hits = 0
                for ex_p in (meta.get("examples") or []):
                    if isinstance(ex_p, str) and ex_p.strip():
                        ex_tokens = set(_tokenize(ex_p))
                        # Partial non-generic overlap: a query sharing a
                        # DISTINCTIVE example token ("naruto" inside
                        # "Is Naruto any good?" vs the example "Search for
                        # the anime Naruto") is a strong declared trigger.
                        # Strict containment misses these; full-overlap
                        # scoring without genericity would let prose words
                        # ("the", "about") boost everything.
                        matched = {
                            t for t in (ex_tokens & q_tokens) if t not in generic
                        }
                        if matched:
                            ex_hits += len(matched)
                kw_hits = 0
                for kw in (meta.get("keywords") or []):
                    if isinstance(kw, str) and kw.strip().lower() in q:
                        kw_tokens = _tokenize(kw)
                        if kw_tokens and kw_tokens[0] not in generic:
                            kw_hits += 1
                total = ex_hits + kw_hits * 3
                if total > 0:
                    boosted.append((cap_name, float(total)))
            boosted.sort(key=lambda t: t[1], reverse=True)
            for cap_name, score in boosted:
                cap_meta = cap_meta_all[cap_name]
                # Recover which signals fired (explanatory, per candidate).
                cand_reasons: list[str] = []
                for ex_p in (cap_meta.get("examples") or []):
                    if isinstance(ex_p, str) and ex_p.strip():
                        ex_tokens = set(_tokenize(ex_p))
                        if {t for t in (ex_tokens & q_tokens) if t not in generic}:
                            cand_reasons.append("example_similarity")
                            break
                for kw in (cap_meta.get("keywords") or []):
                    if isinstance(kw, str) and kw.strip().lower() in q:
                        kw_tokens = _tokenize(kw)
                        if kw_tokens and kw_tokens[0] not in generic:
                            cand_reasons.append(f"keyword:{kw.strip().lower()}")
                results.append(RetrievedCapability(
                    name=cap_name,
                    domain=str(cap_meta.get("domain") or ""),
                    aliases=tuple(cap_meta.get("aliases") or []),
                    score=score,
                    matched_by="example",
                    reasons=tuple(cand_reasons) or ("keyword_match",),
                ))

        # 2. Keyword / domain prefilter → candidate pool.
        candidates: list[str] = []
        kw_map: dict[str, list[str]] = getattr(gc, "capability_keywords", {}) or {}
        query_tokens = _tokenize(q)
        for tok in query_tokens:
            for cap in kw_map.get(tok, []):
                if cap not in candidates:
                    candidates.append(cap)

        # 3. BM25 rank over the pool (or full corpus when pool is empty).
        pool = candidates or [d.name for d in self._docs]
        if pool and self._bm25 is not None:
            query_tokens = _tokenize(q)
            scores = self._bm25.get_scores(query_tokens) if query_tokens else []
            indexed = {d.name: i for i, d in enumerate(self._docs)}
            ranked = sorted(
                ((name, scores[indexed[name]] if name in indexed else 0.0) for name in pool),
                key=lambda t: t[1],
                reverse=True,
            )
            for name, score in ranked[: limit - len(results)]:
                # Zero-score hits carry NO signal (the query shares no tokens
                # with the document) — they must never be returned as
                # candidates: a "Hi" with no tool signal would otherwise
                # surface 15 arbitrary tools and misroute the query to
                # execution (greeting → hallucinated tool call).
                if score <= 0:
                    continue
                meta = (getattr(gc, "capability_index", {}) or {}).get(name, {})
                results.append(RetrievedCapability(
                    name=name,
                    domain=str(meta.get("domain") or ""),
                    aliases=tuple(meta.get("aliases") or []),
                    score=round(float(score), 3),
                    matched_by="bm25",
                    reasons=("bm25",),
                ))

        if not results:
            # 4. Fallback: deterministic name-token overlap (no BM25).
            q_tokens = set(_tokenize(q))
            for doc in self._docs:
                overlap = q_tokens & set(doc.tokens)
                if overlap:
                    results.append(RetrievedCapability(
                        name=doc.name,
                        score=round(len(overlap) * 10.0, 1),
                        matched_by="keyword",
                    ))
            results.sort(key=lambda r: r.score, reverse=True)
            results = results[:limit]

        # Deduplicate (alias hit may also appear in BM25 results).
        seen: set[str] = set()
        deduped: list[RetrievedCapability] = []
        for r in results:
            if r.name not in seen:
                seen.add(r.name)
                deduped.append(r)
        results = deduped[:limit]

        if len(self._cache) > 512:
            self._cache.clear()
        self._cache[key] = results
        logger.info(
            "retriever.completed",
            query=q[:60],
            hits=len(results),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return results

    def invalidate(self) -> None:
        """Clear the retrieval cache (registry recompile / tool changes)."""
        self._cache.clear()
        self._ready = False
        self._docs = []
        self._bm25 = None


_retriever: CapabilityRetriever | None = None
_retriever_fingerprint: str | None = None


def get_capability_retriever() -> CapabilityRetriever:
    """Return the singleton retriever (corpus built on first use).

    The corpus is REBUILT whenever the registry fingerprint changes (tool
    registrations/updates bump the persisted marker, and GlobalContext swaps
    rebuild the indexes): a corpus built against a stale/empty context must
    never keep serving empty results. Metadata-driven — the fingerprint is
    the registry's own version marker.
    """
    global _retriever, _retriever_fingerprint
    try:
        from nexus.compiler.cache import _registry_fingerprint

        current_fp = _registry_fingerprint()
    except Exception:
        current_fp = None
    if (
        _retriever is None
        or (current_fp is not None and _retriever_fingerprint != current_fp)
    ):
        _retriever = CapabilityRetriever()
        _retriever_fingerprint = current_fp
        try:
            from nexus.context.global_context import get_global_context

            _retriever.build_corpus(get_global_context())
        except Exception as exc:
            logger.warning("retriever.init_failed", error=str(exc)[:200])
    return _retriever


def reset_capability_retriever() -> None:
    """Reset the singleton (testing / registry recompile)."""
    global _retriever, _retriever_fingerprint
    _retriever = None
    _retriever_fingerprint = None
