"""P0-A RESOLVER UPGRADE (vNext Phase 1).

Semantic capability metadata + deterministic ranking + dependency closure.

- ``CapabilitySemantics``: machine-readable semantics per capability
  (specificity, generic/fallback, domains, requires). Stored in the tool
  registry's ``validation_rules.semantics`` (no schema migration).
- ``rank_candidates``: final score = base similarity + alias/domain bonuses
  + specificity bonus - generic penalty; a generic fallback is SUPPRESSED
  when a specialized candidate clears the threshold.
- ``close_dependencies``: when a candidate has REQUIRED inputs the query
  cannot provide but ANOTHER capability produces, the producer joins the
  set (coordinates + weather -> geocode_location is added) — the planner
  never operates on an incomplete capability set.

Nemotron proposes; the deterministic ranker decides; Nexus executes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Generic fallback suppression: when the best specialized candidate reaches
# this final score, generic/fallback capabilities are dropped from the set.
_GENERIC_SUPPRESSION_THRESHOLD = 0.70
_GENERIC_PENALTY = 0.35
_SPECIALIZED_BONUS = 0.12
# Marginal-candidate cutoff: candidates whose final score falls more than
# this far below the top candidate are noise (the "search" keyword family
# all match any "search X" query at marginal scores). The planner must see
# the minimum sufficient set — the reviewer's selection principle.
_MARGINAL_CUTOFF = 3.0


@dataclass(frozen=True)
class CapabilitySemantics:
    """Machine-readable semantics for one capability (metadata-driven)."""

    capability_id: str
    specificity: float = 0.5
    generic: bool = False
    fallback: bool = False
    domains: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()

    @classmethod
    def from_registry(cls, name: str, tool_row: Any) -> CapabilitySemantics:
        """Derive semantics from a registry tool row.

        Curated overrides live in ``validation_rules.semantics`` (the
        operator's explicit intent); everything else is derived
        deterministically from the tool's own metadata — REQUIRED inputs
        come from ``input_schema.required`` (the provenance gate's own
        source), produces/consumes from the registry columns, domains from
        the category. Never hardcoded domain logic.
        """
        vr = getattr(tool_row, "validation_rules", None) or {}
        sem = (vr or {}).get("semantics") or {}
        consumes = list(getattr(tool_row, "consumes", None) or [])
        produces = list(getattr(tool_row, "produces", None) or [])
        category = str(getattr(tool_row, "category", "") or "general")
        input_schema = getattr(tool_row, "input_schema", None) or {}
        required = list((input_schema or {}).get("required") or [])
        domains = (
            sem.get("domains")
            if isinstance(sem.get("domains"), list) and sem.get("domains")
            else [category]
        )
        return cls(
            capability_id=name,
            specificity=float(sem.get("specificity", 0.5)),
            generic=bool(sem.get("generic", False)),
            fallback=bool(sem.get("fallback", False)),
            domains=tuple(str(d) for d in domains),
            requires=tuple(str(r) for r in (sem.get("requires") or required)),
            produces=tuple(str(p) for p in produces),
            consumes=tuple(str(c) for c in consumes),
        )


@dataclass
class RankedCandidate:
    """A ranked capability with its evidence trail."""

    name: str
    score: float
    evidence: dict[str, float] = field(default_factory=dict)
    suppressed: bool = False
    suppress_reason: str = ""


def rank_candidates(
    candidates: list[tuple[str, float]],
    semantics_map: dict[str, CapabilitySemantics],
    query: str = "",
    removals: dict[str, str] | None = None,
    apply_marginal_cut: bool = True,
) -> list[RankedCandidate]:
    """Deterministic final ranking with generic suppression.

    final = base_similarity
          + exact_alias_bonus (alias/name token in the query)
          + domain_match_bonus  (domain token in the query)
          + specificity_bonus   (specialized capabilities lift)
          - generic_penalty     (generic/fallback capabilities sink)

    When the best SPECIALIZED candidate clears the suppression threshold,
    generic/fallback candidates are dropped from the result (the
    ``search_meals vs search_web_search`` class — the generic web search
    must not pollute specialized queries).

    Args:
        apply_marginal_cut: When False, the marginal cutoff is deferred to
            the caller (``branch_safe_select`` applies it with the
            distinctness coverage invariant — P0-C).
    """
    q_tokens = set(_tokenize(query))
    ranked: list[RankedCandidate] = []
    for name, base in candidates:
        sem = semantics_map.get(name)
        if sem is None:
            ranked.append(RankedCandidate(name=name, score=base, evidence={"base": base}))
            continue
        evidence: dict[str, float] = {"base": round(base, 3)}
        score = base
        # Alias/name-token bonus: the capability's own name/aliases appear
        # in the query (strong operator signal).
        alias_hit = any(
            bool(_tokenize(alias)) and _tokenize(alias) <= q_tokens
            for alias in sem.domains
        ) or bool(_tokenize(sem.capability_id) <= q_tokens)
        alias_bonus = 0.15 if alias_hit else 0.0
        score += alias_bonus
        evidence["alias"] = alias_bonus
        # Domain bonus.
        domain_bonus = 0.08 if any(d in q_tokens for d in sem.domains) else 0.0
        score += domain_bonus
        evidence["domain"] = domain_bonus
        # Specificity: specialized capabilities lift, generics sink.
        if sem.generic or sem.fallback:
            score -= _GENERIC_PENALTY
            evidence["generic_penalty"] = -_GENERIC_PENALTY
        else:
            score += _SPECIALIZED_BONUS
            evidence["specialized_bonus"] = _SPECIALIZED_BONUS
        ranked.append(RankedCandidate(
            name=name, score=round(score, 3), evidence=evidence,
        ))
    ranked.sort(key=lambda r: -r.score)
    # Generic suppression. Two deterministic triggers (metadata-driven):
    # 1. The best specialized candidate clears the absolute threshold.
    # 2. ANY specialized candidate carries a genuine retrieval signal
    #    (raw base score > 0 — the engine retrieved it) AND the query does
    #    NOT explicitly request the generic fallback ("web"/"internet"/
    #    "online"). The ``search for a meal`` class: the web-search alias
    #    "search" fires at 100 while the specialized meal capability sits
    #    at 1.0 — scale-incomparable raw scores must not let the generic
    #    win a specialized query.
    web_tokens = _tokenize(query)
    explicit_web = bool(web_tokens & {"web", "internet", "online"})
    specialized = [
        r for r in ranked
        if not semantics_map.get(r.name, CapabilitySemantics(r.name)).generic
    ]
    best_specialized = specialized[0] if specialized else None
    if best_specialized and not explicit_web:
        gen_suppress = best_specialized.score >= _GENERIC_SUPPRESSION_THRESHOLD
        gen_suppress = gen_suppress or any(
            r.name == best_specialized.name and r.evidence.get("base", 0) > 0
            for r in specialized
        )
        if gen_suppress:
            for r in ranked:
                sem = semantics_map.get(r.name)
                if sem is not None and (sem.generic or sem.fallback) and r.name != best_specialized.name:
                    r.suppressed = True
                    r.suppress_reason = (
                        f"specialized {best_specialized.name} present "
                        f"(base>0) and no explicit web request"
                    )
                    if removals is not None:
                        removals[r.name] = r.suppress_reason
    # Marginal cutoff: candidates far below the top carry no
    # discriminative signal (the whole search_* family enters every
    # "search X" query via the shared token). Runs AFTER generic
    # suppression (a suppressed generic is already gone; a suppressed
    # list means the specialized candidate won and is kept). The minimum
    # sufficient set for the planner.
    survivors = [r for r in ranked if not r.suppressed]
    if not survivors:
        return survivors
    if not apply_marginal_cut:
        return survivors
    top = survivors[0].score
    if removals is not None:
        for r in survivors[1:]:
            if r.score < top - _MARGINAL_CUTOFF:
                removals[r.name] = (
                    f"below marginal cutoff (top {top}, margin {_MARGINAL_CUTOFF})"
                )
    survivors = [r for r in survivors if r.score >= top - _MARGINAL_CUTOFF]
    return survivors


def branch_safe_select(
    intent_scores: dict[str, list[tuple[str, float]]],
    semantics_map: dict[str, CapabilitySemantics],
) -> tuple[list[tuple[str, float]], dict[str, str]]:
    """P0-A.3: per-intent (branch-local) selection with the coverage
    invariant + removal diagnostics.

    - Each intent unit's candidates are ranked, generics suppressed and
      marginal candidates cut BRANCH-LOCALLY — a candidate belonging to
      one independently-detected intent never disappears because another
      intent has a stronger top (the K83-type multi-intent class).
    - COVERAGE INVARIANT: an intent whose every candidate was removed
      re-admits its top RAW candidate (marked ``coverage_invariant_kept``)
      — every executable intent retains at least one viable capability
      path. The validator's coverage gate still decides semantics.
    - MERGE: the union of per-intent selections (max score per capability).
    - DIAGNOSTICS: ``{capability: removal reason}`` for every name that was
      suppressed/cut/re-admitted — the resolver explains itself.
    """
    selected: dict[str, float] = {}
    diagnostics: dict[str, str] = {}
    # P0-C: two-pass branch selection. Pass 1 ranks + suppresses per branch
    # WITHOUT the marginal cutoff (the coverage truth); the cutoff applies
    # in pass 2 with the DISTINCTNESS invariant (below). This fixes the
    # K83 class: branch 2's raw scores (geocode 100.0 vs reverse_geocode
    # 2.0 — scale-incomparable engine layers) let a shared token's
    # exact-match candidate dominate, and the marginal cutoff then removed
    # the branch's ONLY viable capability. The coverage invariant must hold
    # not only for empty branches, but also when a branch's survivors are
    # all copies of OTHER branches' picks (no branch-distinct capability).
    pass1: dict[str, list[RankedCandidate]] = {}
    for unit, cands in intent_scores.items():
        if not cands:
            continue
        removals: dict[str, str] = {}
        ranked = rank_candidates(
            cands, semantics_map, query=unit, removals=removals,
            apply_marginal_cut=False,
        )
        for name, reason in removals.items():
            diagnostics.setdefault(name, f"{reason} (intent: {unit[:48]})")
        if not ranked:
            top = max(cands, key=lambda c: c[1])
            ranked = [RankedCandidate(
                name=top[0], score=top[1], evidence={"base": top[1]},
            )]
            diagnostics[top[0]] = (
                f"coverage_invariant_kept (intent: {unit[:48]})"
            )
        pass1[unit] = ranked

    # Pass 2: marginal cutoff with the DISTINCTNESS coverage invariant.
    # A branch whose post-cut survivors are all shared with other branches
    # re-admits its top cut candidate — every intent keeps a
    # branch-distinct viable capability (K83: reverse_geocode survives
    # even though geocode_location outscored it 100:2 in branch 2).
    branch_picks: dict[str, set[str]] = {}
    for unit, ranked in pass1.items():
        branch_picks[unit] = {r.name for r in ranked if not r.suppressed}
    for unit, ranked in pass1.items():
        survivors = [r for r in ranked if not r.suppressed]
        if not survivors:
            continue
        top = survivors[0].score
        cut: list[RankedCandidate] = []
        kept: list[RankedCandidate] = []
        for r in survivors:
            if r.score < top - _MARGINAL_CUTOFF:
                cut.append(r)
            else:
                kept.append(r)
        if not kept:
            # All survivors marginal: keep the branch top (coverage).
            top_r = max(ranked, key=lambda r: r.score)
            diagnostics.setdefault(
                top_r.name,
                f"coverage_invariant_kept_all_marginal (intent: {unit[:48]})",
            )
            kept = [top_r]
        elif cut:
            # DISTINCTNESS INVARIANT (P0-C): if every kept candidate is
            # already the pick of ANOTHER branch, this branch loses its
            # only distinct path to the planner — re-admit the top cut
            # candidate, but ONLY when that candidate is itself NOT
            # another branch's pick (it must give this branch a genuinely
            # distinct capability — re-admitting a shared noise candidate
            # like weather into the coordinates branch would pollute the
            # catalog). Metadata-free: cross-branch set comparison.
            other_branch_picks = set()
            for _u, _picks in branch_picks.items():
                if _u != unit:
                    other_branch_picks |= _picks
            if all(r.name in other_branch_picks for r in kept):
                distinct_cut = [
                    r for r in cut if r.name not in other_branch_picks
                ]
                if distinct_cut:
                    top_cut = max(distinct_cut, key=lambda r: r.score)
                    kept.append(top_cut)
                    diagnostics.setdefault(
                        top_cut.name,
                        f"distinctness_invariant_kept (intent: {unit[:48]})",
                    )
        for r in kept:
            if r.name not in selected or r.score > selected[r.name]:
                selected[r.name] = r.score
    return sorted(selected.items(), key=lambda kv: -kv[1]), diagnostics


def close_dependencies(
    candidates: list[tuple[str, float]],
    semantics_map: dict[str, CapabilitySemantics],
    query_entities: set[str],
) -> list[tuple[str, float]]:
    """Dependency closure: add producers for unsatisfied required inputs.

    When a candidate declares REQUIRED inputs (its ``requires``/``consumes``
    as required parameters) that neither the query entities nor the current
    candidate set can supply, and ANOTHER registered capability produces
    them, that producer joins the set. Deterministic, no LLM call.

    The ``coordinates + weather`` class: get_current_weather requires
    latitude/longitude; the query gives "Lahore"; geocode_location
    produces latitude/longitude -> geocode_location is added so the planner
    never operates on an incomplete capability set.

    P0-A.3: the closure is ADDITIVE (producers only ever join) and runs
    AFTER all per-intent cuts — applying it on the merged branch-safe set
    is equivalent to per-branch closure + union (a producer added for one
    intent's consumer is simply part of the merged set; it is never
    marginal-cut away because the closure is the last step).
    """
    available = set(query_entities)
    for name, _s in candidates:
        sem = semantics_map.get(name)
        if sem is not None:
            available |= set(sem.produces)
    result = list(candidates)
    result_names = {name for name, _s in result}
    changed = True
    while changed:
        changed = False
        for name, _score in list(result):
            sem = semantics_map.get(name)
            if sem is None:
                continue
            missing = [
                r for r in sem.requires
                if r and not any(r in e for e in available)
            ]
            for req in missing:
                producers = [
                    (n, s) for n, s in semantics_map.items()
                    if req in s.produces
                ]
                # prefer specialized producers
                producers.sort(key=lambda ps: -ps[1].specificity)
                if not producers:
                    continue  # no registered producer — nothing to close
                best_prod_name = producers[0][0]
                if best_prod_name not in result_names:
                    result.append((best_prod_name, 0.9))
                    result_names.add(best_prod_name)
                    available |= set(producers[0][1].produces)
                    changed = True
    return result


import re  # noqa: E402


def _tokenize(text: str) -> set[str]:

    return set(re.findall(r"[a-zA-Z]{2,}", (text or "").lower()))
