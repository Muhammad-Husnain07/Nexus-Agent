"""Semantic Planner Node — translates natural language to a LogicalWorkflow via LLM.

This is the ONLY LLM call in the critical path that produces structured output.
It receives the Capability Catalog from the DB (logical op names) and uses
``instructor`` to force the LLM to emit a validated ``LogicalWorkflow``.

The LLM is structurally barred from outputting invalid capability names via
a dynamically generated Pydantic ``Literal`` type.  ``instructor`` auto-retries
up to 3 times if the LLM attempts an invalid ``op`` value.

If ``instructor`` is unavailable, falls back to
``response_format={"type": "json_object"}`` with manual validation.

Returns a ``StatePatch`` with ``_logical_workflow`` set.  On parse failure,
returns an error patch.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import typing
from typing import Any

import structlog
from pydantic import ValidationError, create_model

from nexus.agent.node_wrapper import context_node
from nexus.compiler.cache import get_parse_cache
from nexus.compiler.ir_models import LogicalNode, LogicalWorkflow
from nexus.config.settings import get_settings
from nexus.execution.context import ExecutionContext, StatePatch
from nexus.execution.events import emit_planning_completed
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.semantic_planner")

try:
    from nexus.config.settings import get_settings as _sp_settings
    _SP_MAX_NODES = _sp_settings().compiler.max_workflow_nodes
except Exception:
    _SP_MAX_NODES = 50


# ============================================================================
# Capability catalog — fetched from DB at runtime
# ============================================================================


def _scope_out_unavailable(
    valid_ops: list[str],
    replan_context: dict[str, Any] | None,
) -> list[str]:
    """Filter ops marked unavailable by a replan (structural failure or a
    denial that blocked the graph) — they are never re-selected."""
    if not replan_context:
        return valid_ops
    unavailable = set(replan_context.get("unavailable_ops") or [])
    if not unavailable or not valid_ops:
        return valid_ops
    scoped = [op for op in valid_ops if op not in unavailable]
    return scoped if scoped else valid_ops


async def _apply_strong_signal_correction(
    nodes: list[dict[str, Any]],
    query: str,
) -> None:
    """Deterministic strong-signal correction (mutates ``nodes`` in place).

    When the ResolutionEngine's TOP candidate matched via an OPERATOR-DECLARED
    signal (exact alias / example containment / keyword) with a dominant score
    (>= 2x the next candidate), and the plan omitted it entirely, the first op
    is corrected to the engine's pick. Declared metadata outranks the LLM's
    guess — fully engine-driven, no hardcoded names. Applied to cached and
    fresh plans alike so stale LLM mis-selections cannot persist.

    Two additional deterministic cases are covered (observed with weaker
    planner models):
    - EMPTY plan with a dominant signal candidate → the top candidate is
      injected as the plan's single node (a tool query must not degrade to
      conversation when the operator declared a matching trigger).
    - Non-empty plan whose ops carry NO retrieval signal while the top
      candidate holds a declared signal → op[0] is corrected (the LLM
      hallucinated an unrelated tool instead of using the ranked catalog).
    """
    try:
        from nexus.capabilities.resolution_engine import get_resolution_engine

        resolution = await get_resolution_engine().resolve(query, top_k=15)
        caps = resolution.capability_candidates
        if len(caps) < 2:
            return
        top, second = caps[0], caps[1]
        strong_signals = {"exact_alias", "example_similarity", "keyword"}
        dominant = (
            top.score >= 2.0 * second.score
            and bool(strong_signals.intersection(top.match_sources))
        )
        if not dominant:
            # Empty-plan fallback: even WITHOUT dominance, a top candidate
            # carrying ANY operator-declared signal beats a silent empty plan
            # (a tool query must not degrade to "I processed your request"
            # when the operator declared a matching trigger). Only injected
            # when the tool's schema declares NO required inputs — an
            # injected node with empty inputs would be rejected by the plan
            # validator (missing-input) and produce a worse empty response.
            if not nodes:
                try:
                    from nexus.context.global_context import get_global_context

                    _gc = get_global_context()
                except Exception:
                    _gc = None
                for c in caps:
                    if not strong_signals.intersection(c.match_sources):
                        continue
                    if _gc is not None:
                        _meta = (_gc.capability_index or {}).get(c.name) or {}
                        if _meta.get("input_required"):
                            continue
                    nodes.append({
                        "op": c.name,
                        "ref": "StepA",
                        "inputs": {},
                        "depends_on": [],
                    })
                    logger.warning(
                        "semantic_planner.strong_signal_inject_empty",
                        engine_top=c.name,
                        engine_score=c.score,
                    )
                    break
            return

        plan_ops = [str(n.get("op") or "") for n in nodes if isinstance(n, dict)]
        omitted = top.name not in plan_ops

        if not nodes:
            # EMPTY plan → inject the dominant candidate as the single node —
            # ONLY when the tool's schema declares no required inputs (an
            # injected node with empty inputs would be rejected by the plan
            # validator; the honest conversational answer is better).
            try:
                from nexus.context.global_context import get_global_context

                _gc2 = get_global_context()
                _meta2 = (_gc2.capability_index or {}).get(top.name) or {}
                required = bool(_meta2.get("input_required"))
            except Exception:
                required = True
            if required:
                logger.info("semantic_planner.inject_skipped_required_inputs", engine_top=top.name)
                return
            nodes.append({
                "op": top.name,
                "ref": "StepA",
                "inputs": {},
                "depends_on": [],
            })
            logger.warning(
                "semantic_planner.strong_signal_inject_empty",
                engine_top=top.name,
                engine_score=top.score,
            )
            return

        if omitted:
            first = nodes[0]
            if isinstance(first, dict):
                first["op"] = top.name
                logger.warning(
                    "semantic_planner.strong_signal_correction",
                    engine_top=top.name,
                    engine_score=top.score,
                    plan_ops=plan_ops,
                )
    except Exception as exc:
        logger.warning("semantic_planner.strong_signal_failed", error=str(exc)[:150])


def _extract_returns(
    tool_outputs: dict[str, dict[str, Any]],
    name: str,
    cap_name: str,
) -> list[str]:
    """Return the output property names a capability produces.

    ``tool_outputs`` maps capability names to their ``output_schema``
    ``properties`` dicts; a capability without declared outputs yields an
    empty list. Metadata-driven — never assumes a schema exists.
    """
    outputs = tool_outputs.get(name) or tool_outputs.get(cap_name) or {}
    if not isinstance(outputs, dict):
        return []
    return list(outputs.keys())


async def _fetch_capabilities(
    query: str | None = None,
    domain_hint: str | None = None,
    snapshot: dict[str, Any] | None = None,
    intent_graph: Any = None,
) -> tuple[list[str], str]:
    """Fetch the capabilities the planner should consider.

    RETRIEVAL-FIRST via the ResolutionEngine: instead of loading the entire
    catalog, the top-K available capabilities for the effective planning
    message are resolved (BM25 + alias + boost layers + domain narrowing +
    availability facts). The planner's ``Literal`` constraint and prompt
    catalog are built from ONLY those candidates — it never reasons over
    hundreds of unrelated tools. Ranked scores, confidence bands, and match
    sources are rendered into the catalog text (structured candidates stay
    available to callers that need them).

    Args:
        query: The effective planning message (dynamic step intent or
            approval modification when scoped). When None, the full catalog
            is returned (fallback for generic planning).
        domain_hint: Optional deterministic domain to narrow to first.
        intent_graph: P0-C structured decomposition (optional). When present,
            its executable intents' GOALS drive the per-intent branch
            resolution (the resolver maps goals → capabilities; the K83
            anaphoric chain gains its second branch here).

    Returns:
        A tuple of ``(valid_ops, catalog_string)`` — exact ``logical_op_name``
        values for the ``Literal`` type and the human-readable catalog.
    """
    from nexus.capabilities.resolution_engine import get_resolution_engine
    from nexus.context.global_context import get_global_context
    from nexus.db.base import async_session as _cat_db
    from nexus.registry.client import RegistryClient

    valid_ops: list[str] = []
    catalog_parts: list[str] = []

    # P0-A: the capability-semantics map (specificity/generic/requires/
    # produces) is built FIRST — the ranker + dependency closure need it
    # before the resolution candidates are processed.
    _semantics_map: dict[str, Any] = {}
    _tool_schemas: dict[str, dict[str, Any]] = {}
    _tool_outputs: dict[str, dict[str, Any]] = {}
    _tool_examples: dict[str, list[dict[str, Any]]] = {}
    try:
        from sqlalchemy import select as _tool_select  # noqa: PLC0415

        from nexus.db.models.tool import Tool  # noqa: PLC0415

        async with _cat_db() as _sem_db:
            _tool_rows = await _sem_db.execute(
                _tool_select(
                    Tool.name, Tool.input_schema, Tool.output_schema, Tool.examples,
                    Tool.description, Tool.cacheable, Tool.related,
                    Tool.consumes, Tool.produces, Tool.category,
                    Tool.validation_rules,
                )
            )
            for t_row in _tool_rows.all():
                t_name = t_row[0]
                props = (t_row[1] or {}).get("properties", {}) if isinstance(t_row[1], dict) else {}
                if isinstance(props, dict) and props:
                    _tool_schemas[t_name] = props
                out_props = (t_row[2] or {}).get("properties", {}) if isinstance(t_row[2], dict) else {}
                if isinstance(out_props, dict) and out_props:
                    _tool_outputs[t_name] = out_props
                if isinstance(t_row[3], list):
                    _tool_examples[t_name] = [
                        e for e in t_row[3] if isinstance(e, dict) and e.get("user_prompt")
                    ]
                try:
                    from nexus.capabilities.capability_semantics import (
                        CapabilitySemantics,  # noqa: PLC0415
                    )

                    _semantics_map[t_name] = CapabilitySemantics.from_registry(t_name, t_row)
                except Exception:
                    pass
    except Exception:
        pass

    try:
        gc = get_global_context()
        cap_meta: dict[str, dict[str, Any]] = getattr(gc, "capability_index", {}) or {}

        # ResolutionEngine: ranked, availability-filtered candidates + binary
        # workflow facts + typed metadata/explanation (single source of truth).
        candidates: list[Any] = []
        template_hint = ""
        if query and query.strip():
            try:
                resolution = await get_resolution_engine().resolve(
                    query,
                    domain_hint=domain_hint,
                    top_k=15,
                )
                candidates = list(resolution.capability_candidates)
                # P0-A.3 BRANCH-SAFE RESOLUTION (vNext Phase 1): the engine
                # resolves EACH detected intent unit independently; the
                # ranker/suppression/marginal-cut apply BRANCH-LOCALLY so a
                # candidate belonging to one intent never disappears because
                # another intent has a stronger top (the K83-type class).
                # COVERAGE INVARIANT: every intent keeps >= 1 viable path.
                # Dependency closure (additive) runs last on the merged set.
                try:
                    import re as _re  # noqa: PLC0415

                    from nexus.agent.planners.intent_detector import IntentDetector  # noqa: PLC0415
                    from nexus.capabilities.capability_semantics import (  # noqa: PLC0415
                        branch_safe_select,
                        close_dependencies,
                    )

                    _units: list[str] = []
                    try:
                        # P0-C: prefer the STRUCTURED intent graph's goals
                        # (from the adaptive decomposition that ran before
                        # catalog fetch — it may contain intents the clause
                        # splitter never saw, e.g. the K83 anaphoric chain).
                        if intent_graph is not None and getattr(intent_graph, "intents", None):
                            _units = [
                                i.goal for i in intent_graph.executable
                            ] or [query or ""]
                        else:
                            _det = IntentDetector().detect(query or "")
                            if _det is not None and _det.units:
                                _units = [u.text for u in _det.units]
                    except Exception:
                        _units = []
                    if not _units:
                        _units = [query or ""]
                    intent_scores: dict[str, list[tuple[str, float]]] = {}
                    for _u in _units:
                        # P0-A.3: per-intent resolution MUST NOT inherit the
                        # whole-query domain hint — the router's single
                        # domain (e.g. "weather") would filter out the other
                        # intents' capabilities ("Find the coordinates of
                        # Lahore" would lose geocode under a weather hint).
                        # The branch ranker handles specialization.
                        _ures = await get_resolution_engine().resolve(
                            _u, top_k=15,
                        )
                        intent_scores[_u] = [
                            (c.name, float(c.score))
                            for c in _ures.capability_candidates
                        ]
                    selected, diagnostics = branch_safe_select(
                        intent_scores, _semantics_map
                    )
                    closed = close_dependencies(
                        selected, _semantics_map,
                        query_entities=set(
                            _re.findall(r"[a-zA-Z]{3,}", (query or "").lower())
                        ),
                    )
                    candidates = [
                        type("_C", (), {
                            "name": n, "score": s,
                            "confidence": "high", "match_sources": ("resolver_branch",),
                        })()
                        for n, s in closed
                    ]
                    logger.info(
                        "semantic_planner.resolver_branches",
                        units=_units,
                        intent_scores={
                            u: [n for n, _s in sc[:5]] for u, sc in intent_scores.items()
                        },
                        intent_full_scores={
                            u: [(n, round(_s, 2)) for n, _s in sc[:6]]
                            for u, sc in intent_scores.items()
                        },
                        selected=[n for n, _s in selected],
                        closed=[n for n, _s in closed],
                        diagnostics={k: v for k, v in list(diagnostics.items())[:8]},
                    )
                except Exception as _rank_exc:
                    logger.warning(
                        "semantic_planner.resolver_rank_failed",
                        error=str(_rank_exc)[:150],
                    )
                if resolution.workflow_candidates:
                    template_hint = "Suggested workflow template:\n  " + "\n  ".join(
                        f"{w.name} ({w.confidence}, {', '.join(w.match_sources)})"
                        for w in resolution.workflow_candidates[:2]
                    )
                logger.info(
                    "semantic_planner.resolved",
                    query=query[:60],
                    candidates=len(candidates),
                    workflows=len(resolution.workflow_candidates),
                    elapsed_ms=resolution.metadata.elapsed_ms,
                )
            except Exception as exc:
                logger.warning("semantic_planner.resolution_failed", error=str(exc)[:200])

        async with _cat_db() as session:
            registry = RegistryClient(session)
            capabilities = await registry.get_all_capabilities()

            # Tool input/output schemas + examples — the definitive parameter
            # names and returns for each op (metadata-driven, no hardcoding).
            # (the tool rows / schemas / semantics map were already loaded
            # at the top of this function — P0-A)

            # Candidate-driven: the engine's ranked names are authoritative.
            # When resolution produced NOTHING the query carries no tool
            # signal. The planner must NOT see the full catalog for a
            # CONVERSATIONAL request (a catalog invites hallucination: a
            # greeting would plan an arbitrary tool) — it plans nothing →
            # conversational, honest.
            # BENCHMARK FIX: for an EXECUTABLE request (the router already
            # classified it action/workflow) an EMPTY domain is far worse —
            # the planner's Literal becomes unconstrained and the LLM emits
            # invented op names ("get_weather", "get_country_information",
            # "search_docker") that survive into execution. The capability
            # domain must be at least as complete as the resolver's: with
            # zero resolver signal the domain is the FULL registered set
            # (structurally barring invented names; the validator still
            # gates semantics).
            selected_names: set[str] = {c.name for c in candidates} if candidates else set()
            if not selected_names:
                _executable = bool(
                    str(snapshot.get("_query_type") or "") in ("action", "workflow", "analysis")
                    or snapshot.get("_preferred_tools")
                )
                if not _executable:
                    valid_ops = []
                    catalog_parts = []
                    logger.info(
                        "semantic_planner.empty_catalog",
                        query=str(query or "")[:60],
                    )
                    return valid_ops, "".join(catalog_parts)
                logger.info(
                    "semantic_planner.full_domain_fallback",
                    query=str(query or "")[:60],
                    capabilities=len(capabilities),
                )
                selected_names = {cap.logical_op_name or cap.name for cap in capabilities}
                selected_names.discard(None)

            for cap in capabilities:
                name = cap.logical_op_name or cap.name
                if not name:
                    continue
                if selected_names and name not in selected_names:
                    continue
                valid_ops.append(name)

                hints = ""
                policy = cap.input_policy or {}
                defaults = policy.get("defaults", {})
                if defaults:
                    hints = ", ".join(defaults.keys())
                else:
                    schema_props = _tool_schemas.get(name) or _tool_schemas.get(cap.name)
                    if schema_props:
                        # Render schema defaults into the hints so the planner
                        # never invents values for defaulted optional params
                        # (P0-B: the `namespace` class — the LLM filled the
                        # repo name into a field that defaults to "library").
                        parts = []
                        for _pn, _prop in schema_props.items():
                            if isinstance(_prop, dict) and _prop.get("default") is not None:
                                parts.append(f"{_pn}(default={_prop.get('default')})")
                            else:
                                parts.append(_pn)
                        hints = ", ".join(parts)

                meta = cap_meta.get(name) or cap_meta.get(cap.name) or {}
                domain = str(meta.get("domain") or "")
                aliases = list(meta.get("aliases") or [])
                related = list(meta.get("related") or [])
                cacheable = bool(meta.get("cacheable", True))
                desc = str(meta.get("description") or meta.get("purpose") or "")
                returns = _extract_returns(_tool_outputs, name, cap.name)

                entry = name
                if hints:
                    entry += f" (inputs: {hints})"
                if returns:
                    entry += f" | returns: {', '.join(list(returns)[:8])}"
                if domain:
                    entry += f" | domain: {domain}"
                if aliases:
                    entry += f" | aliases: {', '.join(aliases[:4])}"
                if not cacheable:
                    entry += " | non-cacheable"
                # Ranked score + confidence + match sources from the engine —
                # the planner sees determinism, not just names.
                cand = next((c for c in candidates if c.name == name), None)
                if cand is not None:
                    entry += (
                        f" | score: {cand.score:.2f} {cand.confidence}"
                        f" ({', '.join(cand.match_sources)})"
                    )
                # Description + examples enrich the TOP-K candidates only —
                # the full catalog stays lean (few-shot guidance where it
                # matters most, bounded tokens).
                if selected_names and name in selected_names:
                    if desc:
                        entry += f"\n  desc: {desc[:200]}"
                    ex = _tool_examples.get(name) or _tool_examples.get(cap.name) or []
                    if ex:
                        ex_prompts = [str(e.get("user_prompt"))[:80] for e in ex[:2]]
                        entry += f"\n  examples: {' | '.join(ex_prompts)}"
                    if related:
                        entry += f"\n  related: {', '.join(related[:4])}"
                # Ranked catalog: the engine's candidate score determines the
                # listing order (highest first). The planner LLM anchors on
                # the FIRST entries — DB insertion order is not relevance.
                cand = next((c for c in candidates if c.name == name), None)
                score = cand.score if cand is not None else 0.0
                catalog_parts.append((score, entry))

        catalog_parts.sort(key=lambda pair: pair[0], reverse=True)
        catalog = (
            "Available capabilities:\n" + "\n".join(entry for _, entry in catalog_parts)
            if catalog_parts
            else ""
        )
        if template_hint:
            catalog = (catalog + "\n\n" + template_hint) if catalog else template_hint
    except Exception as exc:
        logger.warning("semantic_planner.catalog_db_failed", error=str(exc))

    return valid_ops, catalog


# ============================================================================
# Instructor-backed LLM extraction with strict Literal enforcement
# ============================================================================


async def _instructor_extract(
    prompt: str,
    user_message: str,
    llm: LLMClient,
    model: str,
    session_settings: Any,
    valid_ops: list[str],
) -> dict[str, Any] | None:
    """Use ``instructor`` to extract a validated ``LogicalWorkflow`` from the LLM.

    Dynamically builds a Pydantic model with ``op: Literal[valid_ops]``,
    structurally barring the LLM from outputting invalid capability names.
    ``instructor.max_retries=3`` feeds validation errors back to the LLM for
    self-correction.

    Returns a dict version of the LogicalWorkflow, or ``None`` on failure.
    """
    import importlib
    import os

    try:
        import openai as _openai

        provider, provider_name = llm.registry.resolve_provider(model)
        base_url = provider.config.base_url or ""
        api_key_ref = provider.config.api_key_ref or ""
        api_key = os.environ.get(api_key_ref, "") if api_key_ref else ""

        instructor_mod = importlib.import_module("instructor")
        from_openai = getattr(instructor_mod, "from_openai", None)
        if from_openai is None:
            return None

        client = from_openai(
            _openai.AsyncOpenAI(base_url=base_url, api_key=api_key),
            mode=instructor_mod.Mode.JSON_SCHEMA,
        )

        clean_model = model.split("/", 1)[-1] if "/" in model else model

        # Build StrictLogicalNode with Literal[valid_ops] for the "op" field
        if valid_ops:
            op_literal = typing.Literal[tuple(valid_ops)]  # type: ignore
            StrictLogicalNode = create_model(
                "StrictLogicalNode",
                op=(op_literal, ...),
                __base__=LogicalNode,
            )
            StrictLogicalWorkflow = create_model(
                "StrictLogicalWorkflow",
                nodes=(list[StrictLogicalNode], ...),
                __base__=LogicalWorkflow,
            )
        else:
            StrictLogicalWorkflow = LogicalWorkflow

        workflow: LogicalWorkflow = await client.chat.completions.create(
            model=clean_model,
            response_model=StrictLogicalWorkflow,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=max(session_settings.extraction_max_tokens or 1024, 2048),
            max_retries=3,
        )
        return workflow.model_dump()
    except Exception as exc:
        logger.warning("semantic_planner.instructor_failed", error=str(exc))
        return None


async def _json_extract(
    prompt: str,
    user_message: str,
    llm: LLMClient,
    model: str,
    settings: Any,
) -> dict[str, Any] | None:
    """Fallback: use ``response_format=json_object`` with manual JSON parsing."""
    import re

    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            max_tokens=settings.extraction_max_tokens,
            response_format={"type": "json_object"},
        )

        if response.failed:
            logger.error("semantic_planner.llm_failed", error=response.error)
            return None

        content = response.content or "{}"
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n```$", "", content)

        parsed = json.loads(content)
        if isinstance(parsed, list):
            parsed = {"version": "1.0", "nodes": parsed, "collections": {}}

        if not isinstance(parsed, dict) or "nodes" not in parsed:
            parsed = {"version": "1.0", "nodes": [], "collections": {}}

        try:
            LogicalWorkflow.model_validate(parsed)
        except ValidationError as ve:
            logger.warning("semantic_planner.schema_mismatch", errors=ve.errors())

        return parsed
    except Exception as exc:
        logger.error("semantic_planner.json_extract_failed", error=str(exc))
        return None


# ============================================================================
# P1-C NANO EXTRACTION RECOVERY — bounded, diagnosed, never a blind retry
# ============================================================================
#
# The nano model's stochastic extraction failures MUST NOT all be treated
# as "retry the LLM". Each failure class has a different, cheap recovery:
#
#   EMPTY_PLAN                → planner repair prompt (the detected intent
#                               units are executable — the model skipped them)
#   INVALID_SCHEMA            → schema-constrained repair (the payload is
#                               well-formed but not a LogicalWorkflow)
#   UNKNOWN_CAPABILITY        → deterministic resolver repair (sanitize_ops
#                               already handles; surfaced explicitly)
#   MODEL_TIMEOUT / LLM_ERROR → bounded retry (transient provider failure)
#   MALFORMED_INTENT          → clarify (no executable units at all)
#
# Cap: ONE repair attempt + ONE constrained retry, then PLANNING_FAILED
# (the P1-B status machine surfaces it — never a silent empty plan).

_PLAN_FAILURE_EMPTY = "EMPTY_PLAN"
_PLAN_FAILURE_SCHEMA = "INVALID_SCHEMA"
_PLAN_FAILURE_TIMEOUT = "MODEL_TIMEOUT"
_PLAN_FAILURE_LLM = "LLM_ERROR"


def _diagnose_plan_failure(
    parsed: dict[str, Any] | None,
    extraction_error: str,
    executable_units: list[str],
) -> str:
    """Deterministic diagnosis of a failed planning attempt.

    Args:
        parsed: The extracted payload (None when extraction failed).
        extraction_error: The raw error string from the last attempt.
        executable_units: Detected executable intent goals (P0-C).

    Returns:
        One of the ``_PLAN_FAILURE_*`` class labels.
    """
    err = (extraction_error or "").lower()
    if parsed is None:
        if "timeout" in err or "timed out" in err:
            return _PLAN_FAILURE_TIMEOUT
        return _PLAN_FAILURE_LLM
    nodes = parsed.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return _PLAN_FAILURE_EMPTY
    return _PLAN_FAILURE_SCHEMA


def _chunk_intent_units(
    units: list[str],
    chunk_size: int,
    relationships: list[Any] | None = None,
) -> list[list[str]]:
    """P2-A: split intent units into dependency-respecting chunks.

    The intent graph's units are already in request order (sequence). The
    chunker keeps units in order and groups them into ``chunk_size``-sized
    chunks — dependency relationships (a later unit consuming an earlier
    one's output) are preserved by ordering (the producer precedes its
    consumer in the chunk sequence, and producer+consumer are never split
    across a chunk boundary when the consumer falls in the next chunk —
    the chunk boundary shifts so the pair stays together).

    Returns a list of unit-list chunks (deterministic, order-preserving).
    """
    if not units:
        return []
    if len(units) <= chunk_size:
        return [units]
    # Dependency pairs: (producer_idx, consumer_idx) from relationships.
    rel_pairs: set[tuple[int, int]] = set()
    try:
        for rel in relationships or []:
            src = str(getattr(rel, "source_intent", "") or "")
            tgt = str(getattr(rel, "target_intent", "") or "")
            if not src or not tgt:
                continue
            # Map intent_id -> unit index (goals carry the entity; the
            # relationship ids map to unit order by position).
            src_idx = int(src.rsplit("_", 1)[-1]) - 1 if "_" in src else -1
            tgt_idx = int(tgt.rsplit("_", 1)[-1]) - 1 if "_" in tgt else -1
            if 0 <= src_idx < len(units) and 0 <= tgt_idx < len(units):
                rel_pairs.add((min(src_idx, tgt_idx), max(src_idx, tgt_idx)))
    except Exception:
        rel_pairs = set()

    chunks: list[list[str]] = []
    i = 0
    n = len(units)
    while i < n:
        end = min(i + chunk_size, n)
        # Shift the boundary left so a dependency pair straddling the cut
        # stays together (the consumer moves into the previous chunk).
        for (a, b) in rel_pairs:
            if i < b < end and a < i:
                end = b  # keep consumer b with producer a in the prior chunk
                break
        if end <= i:
            end = i + chunk_size
        chunks.append(units[i:end])
        i = end
    return chunks


async def _chunked_plan_extract(
    llm: LLMClient,
    model: str,
    user_message: str,
    units: list[str],
    capabilities: str,
    valid_ops: list[str],
    settings: Any,
    budget: Any,
    relationships: list[Any] | None = None,
) -> dict[str, Any] | None:
    """P2-A hierarchical planning: extract ONE plan per chunk, merge.

    For mega-intent requests (20+ units) the single structured extraction
    over the whole request fails (``got []`` — the T132/U133/W135/S126
    class). Chunked planning asks the model for a small plan per
    dependency-ordered chunk, then merges the node lists. Each chunk's
    prompt names ONLY that chunk's units + the capability catalog — the
    model never reasons over the entire 25-node workflow at once.

    Returns the merged workflow dict, or None on failure.
    """
    from nexus.agent.prompts.manager import prompt_manager as _ch_pm

    chunk_size = 6
    try:
        chunk_size = int(get_settings().compiler.chunk_size)
    except Exception:
        chunk_size = 6
    chunks = _chunk_intent_units(units, chunk_size, relationships)
    if not chunks or len(chunks) < 2:
        return None
    merged_nodes: list[dict[str, Any]] = []
    used_refs: set[str] = set()
    # P2-A.5 timing instrumentation: per-chunk LLM latency (the planning
    # critical path for mega-DAGs).
    chunk_llm_ms: list[float] = []

    async def _plan_chunk(ci: int, chunk: list[str]) -> list[dict[str, Any]]:
        """Extract one chunk's plan (independent — parallelizable)."""
        if not budget.consume("llm_calls"):
            logger.warning("semantic_planner.chunked_budget_exhausted", chunk=ci)
            return []
        _t0 = time.perf_counter()
        chunk_prompt = _ch_pm.render(
            "logical_planner", "2.4",
            capabilities=capabilities if capabilities else "(none available)",
            history="(chunked hierarchical planning — plan ONLY the listed units)",
        )
        chunk_user = (
            f"Plan the following intent units ONLY (chunk {ci + 1}/{len(chunks)}):\n"
            + "\n".join(f"- {u}" for u in chunk[:8])
        )
        parsed = await _instructor_extract(
            chunk_prompt, chunk_user, llm, model, settings, valid_ops
        )
        if parsed is None:
            parsed = await _json_extract(chunk_prompt, chunk_user, llm, model, settings)
        chunk_llm_ms.append(round((time.perf_counter() - _t0) * 1000, 1))
        nodes = parsed.get("nodes") if isinstance(parsed, dict) else None
        if not isinstance(nodes, list) or not nodes:
            logger.warning("semantic_planner.chunked_empty", chunk=ci)
            return []
        out: list[dict[str, Any]] = []
        for node in nodes:
            if isinstance(node, dict):
                out.append(dict(node))
        return out

    # P2-A: chunks are dependency-ORDERED groups — parallel extraction is
    # safe because each chunk plans ONLY its own units (no cross-chunk
    # references in the prompts). Merging re-sequences by chunk order.
    _chunk_results = await asyncio.gather(*[
        _plan_chunk(ci, chunk) for ci, chunk in enumerate(chunks)
    ])
    # P2-A.5: the planning critical path — chunk LLM latencies (parallel,
    # so max ≈ wall), chunk count, merge size.
    logger.info(
        "semantic_planner.chunk_timing",
        chunk_count=len(chunks),
        chunk_parallel=True,
        per_chunk_llm_ms=chunk_llm_ms,
        max_chunk_ms=max(chunk_llm_ms, default=0.0),
        sum_chunk_ms=round(sum(chunk_llm_ms), 1),
        planned_chunks=sum(1 for r in _chunk_results if r),
    )
    for ci, chunk_nodes in enumerate(_chunk_results):
        for node in chunk_nodes:
            ref = str(node.get("ref") or f"chunk{ci}_{len(used_refs)}")
            if ref in used_refs:
                ref = f"{ref}_{ci}"
            node["ref"] = ref
            used_refs.add(ref)
            merged_nodes.append(node)
    if not merged_nodes:
        return None
    # P2-A.1 COVERAGE INVARIANT AT THE MERGE: a chunk unit whose capability
    # the model skipped (T132's ``reverse-geocoded location`` unit → no
    # ``reverse_geocode`` node) is recovered DETERMINISTICALLY — resolve
    # the unit through the same engine the branch solver uses and add the
    # top available candidate as a node. The model proposes; the
    # deterministic resolver guarantees coverage (the chunked analogue of
    # the branch-safe coverage invariant).
    try:
        from nexus.capabilities.resolution_engine import get_resolution_engine  # noqa: PLC0415
        from nexus.context.global_context import get_global_context as _cov_gc  # noqa: PLC0415

        _engine = get_resolution_engine()
        _gc = _cov_gc()
        _merged_ops = {str(n.get("op") or "") for n in merged_nodes}
        for unit in units:
            _u_low = unit.lower()
            # Covered = the merged plan has an op whose registry
            # keyword/alias bridge matches the unit (metadata-driven —
            # never op-name substring guessing).
            _matched = False
            try:
                from nexus.agent.planners.intent_detector import unit_candidates  # noqa: PLC0415

                _cands = unit_candidates(
                    type("U", (), {"text": unit.replace("-", " "), "negated": False,
                                   "order": 0, "instance_hint": 1,
                                   "comparison": False, "confidence": 1.0})(),
                    _gc,
                )
                if _merged_ops & set(_cands):
                    _matched = True
            except Exception:
                _matched = False
            if not _matched:
                # Fallback: engine rank for the unit — the top available
                # candidate is the deterministic pick. Hyphenated units
                # ("reverse-geocoded location") tokenize as one word —
                # normalize hyphens to spaces so the keyword bridge sees
                # the intended tokens.
                _res = await _engine.resolve(unit.replace("-", " "), top_k=5)
                _top = next(
                    (c for c in _res.capability_candidates if c.availability == "available"),
                    None,
                )
                if _top is not None and _top.name not in _merged_ops:
                    merged_nodes.append({
                        "op": _top.name,
                        "ref": f"cov_{len(merged_nodes)}",
                        "inputs": {},
                        "depends_on": [],
                    })
                    _merged_ops.add(_top.name)
                    logger.info(
                        "semantic_planner.chunk_coverage_added",
                        unit=unit[:40],
                        op=_top.name,
                    )
    except Exception as _cov_exc:
        logger.warning("semantic_planner.chunk_coverage_failed", error=str(_cov_exc)[:150])
    return {"version": "1.0", "nodes": merged_nodes, "collections": {}}


async def _repair_empty_plan(
    llm: LLMClient,
    model: str,
    user_message: str,
    executable_units: list[str],
    capabilities: str,
    valid_ops: list[str],
    budget: Any,
) -> dict[str, Any] | None:
    """ONE constrained repair call for the EMPTY_PLAN class.

    The model produced ``nodes: []`` while executable intent units exist —
    the repair prompt names the units and the available capabilities
    (never a blind re-prompt of the original planner).
    """
    if not executable_units or not budget.consume("llm_calls"):
        return None
    prompt = (
        "You must plan at least one operation. The user's request contains "
        "the following executable intent units that you previously omitted:\n"
        + "\n".join(f"- {u}" for u in executable_units[:6]) +
        "\n\nUse ONLY these capabilities (exact names):\n" +
        ", ".join(valid_ops[:20]) +
        "\n\nReturn ONLY JSON: {\"version\":\"1.0\",\"nodes\":[{\"op\":str,"
        "\"ref\":str,\"inputs\":{},\"depends_on\":[]}],\"collections\":{}}"
    )
    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "You are a deterministic plan extractor. Plan one node "
                    "per executable intent unit using the exact capability "
                    "names provided. Only output JSON."
                )},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        if response.failed or not response.content:
            logger.warning("semantic_planner.repair_llm_failed", error=str(response.error)[:150])
            return None
        content = re.sub(r"^```[a-zA-Z]*\n?", "", str(response.content))
        content = re.sub(r"\n```$", "", content)
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return None
        parsed = json.loads(content[start:end + 1])
        nodes = parsed.get("nodes")
        if isinstance(nodes, list) and nodes:
            # Constrain to registered capabilities (deterministic).
            constrained = [
                n for n in nodes
                if isinstance(n, dict) and str(n.get("op") or "") in valid_ops
            ]
            if constrained:
                parsed["nodes"] = constrained
                return parsed
        return None
    except Exception as exc:
        logger.warning("semantic_planner.repair_failed", error=str(exc)[:150])
        return None


# ============================================================================
# Conversation history formatter
# ============================================================================


def _sanitize_ops(
    nodes: list[dict[str, Any]],
    valid_ops: list[str],
    domain_hint: str | None = None,
) -> list[dict[str, Any]]:
    """Remap LLM-invented capability names onto the registered catalog.

    Layered, deterministic resolution — never guesses below the fuzzy
    threshold:

    L1 exact   → op is already in the catalog
    L2 domain  → op resolves within the domain-scoped candidate set
    L3 alias   → explicit operator-declared alias (O(1))
    L4 fuzzy   → RapidFuzz at the configured threshold (default ≥95)

    Nodes that fail every layer are REMOVED and their op names are
    collected on ``node["_unresolved_ops"]`` so the caller can run LLM
    repair (top-K) or surface an explicit error — never silently dropped.
    Fully metadata-driven: candidates, aliases, and domains come from the
    live registry (GlobalContext).

    Args:
        nodes: Extracted logical nodes.
        valid_ops: Registered capability names (``logical_op_name`` values).
        domain_hint: Optional domain to narrow the search space first.

    Returns:
        Sanitized node list; unresolved ops recorded on each node.
    """
    if not valid_ops:
        return nodes

    from nexus.capabilities.resolution import (
        LAYER_ALIAS,
        LAYER_DOMAIN,
        LAYER_EXACT,
        LAYER_FUZZY,
        resolve_operation,
    )
    from nexus.context.global_context import get_global_context

    gc = get_global_context()
    alias_index = getattr(gc, "alias_index", {}) or {}
    domain_index = getattr(gc, "domain_index", {}) or {}

    cleaned: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        op = str(node.get("op") or "")
        if op in valid_ops:
            cleaned.append(node)
            continue

        result = resolve_operation(
            op,
            alias_index=alias_index,
            domain_index=domain_index,
            domain_hint=domain_hint,
            catalog=valid_ops,
        )
        if result.op is not None and result.layer in (LAYER_EXACT, LAYER_DOMAIN, LAYER_ALIAS, LAYER_FUZZY):
            logger.info(
                "semantic_planner.op_resolved",
                requested=op,
                resolved=result.op,
                layer=result.layer,
                confidence=result.confidence,
                elapsed_ms=result.elapsed_ms,
            )
            node["op"] = result.op
            cleaned.append(node)
        else:
            # Keep the node so the caller can repair or surface the error.
            node.setdefault("_unresolved_ops", []).append(op)
            logger.warning(
                "semantic_planner.op_unresolvable",
                op=op,
                layer=result.layer,
                confidence=result.confidence,
            )
            cleaned.append(node)
    return cleaned


def _drop_unresolved(
    nodes: list[dict[str, Any]],
    valid_ops: list[str],
) -> list[dict[str, Any]]:
    """Drop nodes whose op is not in the valid catalog (never execute).

    Used by the cache-hit path: sanitize collects ``_unresolved_ops`` but
    cached plans have no LLM available for repair — unresolved ops are
    removed so execution never touches them (their names are recorded on
    the returned nodes' ``_cache_dropped_ops`` for the caller to surface).

    Args:
        nodes: Sanitized logical nodes.
        valid_ops: Resolvable capability names.

    Returns:
        Nodes with only resolvable ops.
    """
    surviving: list[dict[str, Any]] = []
    dropped: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            surviving.append(node)
            continue
        op = str(node.get("op") or "")
        if op in valid_ops:
            surviving.append(node)
        else:
            dropped.append(op)
    if dropped:
        surviving.append({"_cache_dropped_ops": dropped})
        logger.warning("semantic_planner.cache_dropped_ops", dropped=dropped)
    return surviving


def _surface_cache_drops(workflow: dict[str, Any]) -> list[str]:
    """Move ``_cache_dropped_ops`` markers out of the workflow.

    Returns the dropped op names so the caller can surface them as errors
    on the state patch (never inside the strict LogicalWorkflow dict).
    """
    dropped: list[str] = []
    clean_nodes: list[dict[str, Any]] = []
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if "_cache_dropped_ops" in node:
            dropped.extend(node["_cache_dropped_ops"])
        else:
            clean_nodes.append(node)
    workflow["nodes"] = clean_nodes
    if dropped:
        logger.warning("semantic_planner.cache_dropped_ops", dropped=dropped)


def _plan_unsafe_to_cache(nodes: list[Any], user_query: str = "") -> bool:
    """True when a plan must never enter the ParseCache (D0/P0-C, I11).

    A plan is unsafe to cache when it is structurally invalid in a
    statically-detectable way: schema-invalid input values, missing
    REQUIRED inputs, INVENTED input keys (keys the capability schema does
    not declare), or REQUIRED-input literal values that lack message
    provenance (the F4-class replay: a bad-but-well-formed plan cached and
    replayed deterministically — scenario 35's ``base_currency`` value).
    Caching such a plan turns a one-off LLM mistake into a deterministic
    replay.
    """
    if _has_schema_invalid_nodes(nodes):
        return True
    try:
        from nexus.agent.nodes.plan_validator_node import (
            _unknown_input_keys,
            _value_in_message,
        )
    except Exception:
        return False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        op = str(node.get("op") or "")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        if _unknown_input_keys(op, inputs):
            return True
        # VALUE PROVENANCE (I11 extension, P1-A/A1): a REQUIRED input
        # carrying a literal value that appears nowhere in the user message
        # is a guessed value — caching it replays the guess forever. The
        # planner has the message at write time; this is deterministic.
        if not user_query:
            continue
        from nexus.agent.nodes.plan_validator_node import _capability_meta

        meta = _capability_meta(op)
        required = set(meta.get("input_required") or [])
        for key, value in inputs.items():
            if key not in required:
                continue
            if not isinstance(value, (str, int, float)):
                continue
            if isinstance(value, str) and (
                not value.strip()
                or value.startswith("${")
            ):
                continue
            if not _value_in_message(value, user_query):
                return True
    return False


def _has_schema_invalid_nodes(nodes: list[Any]) -> bool:
    """True when any node carries an input the tool's declared JSON Schema
    type can never accept (garbage values the model emitted once, e.g.
    ``"temperature"`` for a boolean param), OR is missing a REQUIRED input
    (an injected/empty node would be rejected by the plan validator and
    produce an empty response). Schema/type metadata comes from the registry
    (GC meta) — metadata-driven, never hardcoded."""
    try:
        from nexus.agent.nodes.plan_validator_node import (
            _missing_inputs,
            _schema_type_violations,
        )
    except Exception:
        return False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        op = str(node.get("op") or "")
        if not op:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or not inputs:
            inputs = {}
        if _schema_type_violations(op, inputs):
            return True
        provided = {
            k for k, v in inputs.items()
            if not (isinstance(v, str) and not v.strip())
        }
        if _missing_inputs(op, provided):
            return True
    return False


def _coverage_uncovered_candidates(
    snapshot: dict[str, Any], valid_ops: list[str]
) -> list[str]:
    """F8-B: deterministic candidate capability names for UNCOVERED intents.

    The planner's ``valid_ops`` scope is built from whole-QUERY resolution,
    which can return too few candidates (the F8 mechanism: the query-level
    engine scored only the first of two parallel intents, so the instructor
    ``Literal[valid_ops]`` structurally barred the second capability). The
    VALIDATOR's per-UNIT resolution (intent_coverage_evidence) knows the
    correct candidates — this returns them so the replan can widen the
    structural scope.

    Safety: every returned name is (a) engine-computed by the validator's
    coverage evidence (never LLM-generated), and (b) verified to exist in
    the GlobalContext capability index (a registered capability).
    Deterministic, deduplicated, sorted.
    """
    if not valid_ops:
        return []
    errors = snapshot.get("_plan_validator_errors") or []
    if not any("intent coverage" in str(e) for e in errors):
        return []
    _report = snapshot.get("_plan_validator_report") or {}
    if not isinstance(_report, dict):
        return []
    evidence = (_report.get("metrics") or {}).get("intent_coverage_evidence")
    if not isinstance(evidence, list) or not evidence:
        return []
    found: set[str] = set()
    for rec in evidence:
        if not isinstance(rec, dict):
            continue
        if rec.get("served") is not False:
            continue
        if rec.get("negated") is True or rec.get("classifiable") is not True:
            continue
        for c in rec.get("candidates") or []:
            if not isinstance(c, str) or not c:
                continue
            try:
                from nexus.agent.nodes.plan_validator_node import _capability_meta  # noqa: PLC0415

                if not _capability_meta(c):
                    continue  # not a registered capability — never inject
            except Exception:
                continue
            found.add(c)
    return sorted(found)


def _coverage_evidence_feedback(
    snapshot: dict[str, Any], valid_ops: list[str]
) -> str | None:
    """F8-B: deterministic capability candidates for UNCOVERED intents.

    Returns a structured prompt block (or ``None`` when nothing is
    actionable): for every classifiable, non-negated executable intent the
    validator marked unserved, list its engine-computed candidate
    capabilities (NAMES ONLY — never scores, never ranking internals,
    never LLM-generated capabilities). The evidence is produced by the
    deterministic validator's own coverage computation and filtered to
    ``valid_ops`` before injection.

    The planner still decides WHAT operation to construct — this only
    informs the repair so the model does not have to independently
    rediscover capability resolution from natural language (the F8
    failure mode). First-pass planning is untouched: this runs only on
    the replan path after an intent-coverage rejection.
    """
    if not valid_ops:
        return None
    errors = snapshot.get("_plan_validator_errors") or []
    if not any("intent coverage" in str(e) for e in errors):
        return None
    _report = snapshot.get("_plan_validator_report") or {}
    if not isinstance(_report, dict):
        return None
    evidence = (_report.get("metrics") or {}).get("intent_coverage_evidence")
    if not isinstance(evidence, list) or not evidence:
        return None
    lines: list[str] = []
    for rec in evidence:
        if not isinstance(rec, dict):
            continue
        if rec.get("served") is not False:
            continue  # covered intents need no candidate feedback
        if rec.get("negated") is True or rec.get("classifiable") is not True:
            continue  # negative/unclassifiable intents are never planned
        unit = str(rec.get("unit") or "").strip()
        candidates = sorted({
            c for c in (rec.get("candidates") or [])
            if isinstance(c, str) and c in valid_ops
        })
        if not candidates:
            continue
        lines.append(
            f'UNCOVERED INTENT: "{unit}"\n'
            "DETERMINISTIC CAPABILITY CANDIDATES (registered capabilities only):\n"
            + "\n".join(f"  - {c}" for c in candidates)
        )
    if not lines:
        return None
    return (
        "UNCOVERED INTENTS REQUIRE OPERATIONS\n"
        + "\n\n".join(lines)
        + "\n\nREQUIREMENT: create an operation for EACH uncovered intent using one "
        "of its deterministic candidate capabilities. Do not assign a capability "
        "that is not among an intent's candidates, and do not reuse a capability "
        "already assigned to another intent unless it is semantically correct for "
        "that intent."
    )


async def _repair_ops(
    llm: LLMClient,
    model: str,
    unresolved: list[str],
    candidates: list[str],
) -> dict[str, str]:
    """LLM repair (last resort) — map unresolved ops onto top-K candidates.

    Only called after every deterministic layer failed. The prompt contains
    ONLY the top-K candidates (default 5) — never the full catalog. Returns
    ``{unresolved_op: resolved_op}`` for the names the LLM can map; callers
    surface the remainder as explicit errors.

    Args:
        llm: LLM client.
        model: Model id.
        unresolved: Op names that failed deterministic resolution.
        candidates: Top-K candidate capability names.

    Returns:
        Mapping of resolved names (subset of ``unresolved``).
    """
    if not unresolved or not candidates:
        return {}

    try:
        from nexus.config.settings import get_settings as _repair_settings

        max_k = _repair_settings().resolver.max_repair_candidates
    except Exception:
        max_k = 5
    top = candidates[:max_k]

    system_prompt = (
        "You are mapping capability names to the closest registered "
        "capability. Return JSON: {\"mapping\": {\"<requested>\": \"<closest>\"}} "
        "using ONLY names from the provided list. Omit names with no close match."
    )
    prompt = (
        f"Registered candidates: {', '.join(top)}\n"
        f"Requested names: {', '.join(unresolved)}"
    )
    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt[:800]},
            ],
            temperature=0,
            max_tokens=128,
            response_format={"type": "json_object"},
        )
        if response.failed:
            logger.warning("semantic_planner.repair_llm_failed", error=response.error)
            return {}
        data = json.loads(response.content or "{}")
        mapping = data.get("mapping", {})
        if not isinstance(mapping, dict):
            return {}
        valid = {c: True for c in candidates}
        return {
            str(k): str(v)
            for k, v in mapping.items()
            if str(k) in unresolved and str(v) in valid
        }
    except Exception as exc:
        logger.warning("semantic_planner.repair_failed", error=str(exc)[:200])
        return {}


async def _match_template(query: str) -> list[dict[str, Any]] | None:
    """Try to match a WorkflowTemplate for the given query.

    If matched, the capability chain is expanded recursively and returned
    as a suggested starting point for the planner.
    """
    try:
        from nexus.capabilities.template_engine import expand_template_chain, match_template
        chain = await match_template(query)
        if chain:
            expanded = await expand_template_chain(chain)
            if expanded:
                logger.info(
                    "semantic_planner.template_matched",
                    steps=len(expanded),
                )
                return expanded
    except Exception as exc:
        logger.warning("semantic_planner.template_match_failed", error=str(exc))
    return None


def _format_template_hint(chain: list[dict[str, Any]]) -> str:
    """Format a matched template chain as a human-readable hint for the LLM."""
    lines = ["The following workflow template was found for this request:"]
    for i, step in enumerate(chain, 1):
        cap = step.get("capability", step.get("template", "unknown"))
        inputs = step.get("inputs", {})
        hints = ", ".join(f"{k}={v}" for k, v in inputs.items()) if inputs else ""
        lines.append(f"  {i}. {cap}" + (f" ({hints})" if hints else ""))
    return "\n".join(lines)

def _format_history(messages: list) -> str:
    """Format prior conversation turns for anaphora resolution.

    Shows up to 3 prior exchanges (6 prior messages), excluding the
    current user message which is sent separately to the LLM.
    The LLM uses this to resolve pronouns and contextual references.
    """
    # Exclude the last message (current user query) from history
    prior = messages[:-1] if len(messages) > 1 else []
    recent = prior[-6:] if len(prior) > 6 else prior
    lines = []
    for msg in recent:
        if isinstance(msg, dict):
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _prior_plan_context(snapshot: dict) -> tuple[list[str], str]:
    """The previous turn's executed tools (metadata-driven).

    Reads the state's execution graph (physical nodes with tool names in
    execution order) and returns (tool_names, chain_text). Empty when there
    is no prior execution — never hardcoded.
    """
    graph = snapshot.get("_execution_graph") or {}
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, dict) or not nodes:
        return [], ""
    tools: list[str] = []
    for nid, ndata in nodes.items():
        if not isinstance(ndata, dict):
            continue
        name = ndata.get("tool_name") or ndata.get("capability")
        if name and name not in tools:
            tools.append(name)
    if not tools:
        return [], ""
    return tools, " -> ".join(tools)


# ============================================================================
# Graph node
# ============================================================================


@context_node
async def semantic_parser_node(
    ctx: ExecutionContext,
    llm: LLMClient,
    model: str,
) -> StatePatch:
    """Translate the user message into a LogicalWorkflow via LLM.

    1. Fetch capabilities from DB (``valid_ops`` list + prompt catalog).
    2. Check ParseCache — if hit, return cached LogicalWorkflow (no LLM).
    3. If miss, make ONE LLM call with ``instructor`` and strict ``Literal``.
    4. Store in ParseCache for future hits.
    """
    snapshot = ctx.snapshot
    messages = snapshot.get("messages", [])
    last_message = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_message = str(m.get("content", ""))
            break
        if hasattr(m, "role") and m.role == "user":
            last_message = str(getattr(m, "content", ""))
            break

    # HYBRID: a workflow's dynamic step routes here with its own intent
    # description — plan THAT step instead of the raw user message.
    dynamic_intent = snapshot.get("_workflow_dynamic_intent")
    if dynamic_intent:
        last_message = str(dynamic_intent)

    # APPROVAL MODIFICATION: the user altered a pending operation — plan the
    # modified request instead of the original one.
    modification = snapshot.get("_approval_modification")
    if modification:
        last_message = str(modification)

    if not last_message:
        return StatePatch(
            version=ctx.version + 1,
            updates={
                "_logical_workflow": None,
                "_extraction_result": {},
            },
        )

    # Try to match a WorkflowTemplate to pre-fill the capabilities catalog
    template_chain = await _match_template(last_message)

    # Domain-first: the router's deterministic domain hint narrows the
    # catalog before the LLM reasons (the ResolutionEngine scopes candidates
    # to the domain as one of its metadata layers).
    domain_hint = snapshot.get("_domain_hint")

    # P0-C ADAPTIVE STRUCTURED DECOMPOSITION: BEFORE capability fetch, so
    # the intent graph drives the resolver's per-intent branches (the K83
    # anaphoric chain must enter the catalog as TWO goals, not one). The
    # deterministic compound-signal trigger decides whether the Tier-2 LLM
    # decomposer is worth its call — simple queries score ~0 (no extra
    # LLM call), compound/anaphoric queries fire (the reviewer's
    # latency discipline). The graph is stored on the snapshot so the
    # validator's coverage check consumes the SAME detected intents.
    intent_graph: Any = None
    try:
        from nexus.agent.planners.intent_detector import (
            IntentDetector,
            _compound_signal_strength,
        )

        _tier1 = IntentDetector()
        intent_graph = _tier1.detect_graph(last_message)
        _trigger = _compound_signal_strength(last_message)
        _replanning_now = bool(
            snapshot.get("_plan_validator_errors") or snapshot.get("_compile_errors")
        )
        _intent_repair_failed = any(
            any(code in str(e) for code in ("intent coverage", "empty plan",
                                            "extraneous", "not served"))
            for e in (snapshot.get("_plan_validator_errors") or [])
        )
        if (_trigger >= 0.45 or _intent_repair_failed or _replanning_now):
            from nexus.agent.planners.intent_decomposer_llm import decompose_with_llm  # noqa: PLC0415

            llm_graph = await decompose_with_llm(llm, model, last_message)
            if llm_graph is not None and llm_graph.intents:
                intent_graph = llm_graph
                logger.info(
                    "semantic_planner.llm_decomposition",
                    intents=[i.goal[:50] for i in llm_graph.executable],
                    relationships=[
                        f"{r.source_intent}->{r.target_intent}" for r in llm_graph.relationships
                    ],
                    trigger=round(_trigger, 2),
                )
        logger.info(
            "semantic_planner.intent_graph",
            intents=[i.goal[:50] for i in intent_graph.executable],
            relationships=len(intent_graph.relationships),
            source=intent_graph.source,
            trigger=round(_trigger, 2),
        )
    except Exception as exc:
        logger.warning("semantic_planner.intent_detect_failed", error=str(exc)[:150])

    # Fetch capabilities — RETRIEVAL-FIRST via the ResolutionEngine: the
    # effective planning message (dynamic step intent / approval modification
    # when scoped) narrows the catalog to ranked, available top-K candidates
    # before the LLM ever sees it. Engine facts + scored catalog text.
    valid_ops, capabilities = await _fetch_capabilities(
        last_message, domain_hint=domain_hint, snapshot=snapshot,
        intent_graph=intent_graph,
    )

    # Replan scoping: ops marked unavailable by a replan (structural failure)
    # or an approval denial that blocked the graph are never re-selected.
    replan_context = snapshot.get("_replan_context") or {}
    scoped_ops = _scope_out_unavailable(valid_ops, replan_context)
    if scoped_ops != valid_ops:
        valid_ops = scoped_ops
        logger.info("semantic_planner.replan_scoped", excluded=sorted(replan_context.get("unavailable_ops") or []))
    if template_chain:
        template_hint = _format_template_hint(template_chain)
        if capabilities:
            capabilities += "\n\nSuggested workflow template:\n" + template_hint
        else:
            capabilities = "Suggested workflow template:\n" + template_hint

    # Follow-up planning context: the PREVIOUS turn's executed chain is used
    # ONLY as a continuation-sensitivity component of the parse-cache key
    # (``prior_chain`` below) so cached plans never leak across conversation
    # contexts. It is deliberately NOT injected into the catalog: a catalog
    # note inviting mirroring made the model re-plan the prior chain with the
    # CURRENT message as the new input (e.g. geocode("List Studio Ghibli
    # films…")), destroying otherwise-correct plans. Continuation queries
    # ("And in Osaka?") are covered by the engine's own retrieval (geocode/
    # weather rank in its top-K), and scoped planning (dynamic workflow
    # steps / approval modifications) must see ONLY their intent.
    _scoped = bool(
        snapshot.get("_workflow_dynamic_pending")
        or snapshot.get("_approval_modification")
    )
    history_for_plan = "" if _scoped else _format_history(messages)
    _, prior_chain = _prior_plan_context(snapshot) if not _scoped else ([], "")

    # Replan feedback: the deterministic PlanValidatorNode rejected the
    # previous plan — surface its errors so the replan avoids them.
    validator_errors = snapshot.get("_plan_validator_errors") or []
    compile_errors = snapshot.get("_compile_errors") or []
    feedback_items = [
        *(str(e) for e in validator_errors[:5]),
        *(str(e) for e in compile_errors[:5]),
    ]
    if feedback_items:
        note = "Previous plan was rejected:\n  - " + "\n  - ".join(feedback_items)
        capabilities = (capabilities + "\n\n" + note) if capabilities else note

    # F8-B EVIDENCE-DIRECTED REPAIR: an intent-coverage rejection means the
    # LLM extraction dropped or mis-resolved an intent. Two effects, both
    # deterministic and evidence-only:
    #
    # 1. STRUCTURAL SCOPE WIDENING: valid_ops (the instructor Literal) is
    #    built from whole-query resolution, which can bar the uncovered
    #    intent's capabilities outright (F8: query-level resolution scored
    #    only the first of two parallel intents). The validator's per-unit
    #    candidates widen the scope so the model is STRUCTURALLY ABLE to
    #    plan them. The planner still decides what to construct.
    # 2. PROMPT EVIDENCE: the candidates are surfaced in the replan note so
    #    the model knows exactly which capabilities may serve each uncovered
    #    intent — no scores, no ranking internals, no extra LLM call.
    uncovered_cands = _coverage_uncovered_candidates(snapshot, valid_ops)
    if uncovered_cands:
        valid_ops = list(dict.fromkeys([*valid_ops, *uncovered_cands]))
    coverage_note = _coverage_evidence_feedback(snapshot, valid_ops)
    if coverage_note:
        logger.info(
            "semantic_planner.coverage_evidence_injected",
            chars=len(coverage_note),
            scope_added=len(uncovered_cands),
        )
        capabilities = (capabilities + "\n\n" + coverage_note) if capabilities else coverage_note

    # P4-4 ADAPTIVE INTENT DECOMPOSITION — moved BEFORE capability fetch
    # (P0-C): the structured intent graph now drives the resolver's
    # per-intent branches and the validator's coverage check; it is no
    # longer a post-hoc repair signal computed after the catalog exists.

    # Planning memory (Phase 5): preferences / prior tasks / recurring goals
    # retrieved before the LLM reasons — bounded, session-scoped, typed.
    try:
        from nexus.memory.scout import MemoryScout

        _session_id = snapshot.get("session_id", "")
        _memory = await MemoryScout().scout_for_planning(
            last_message,
            session_id=str(_session_id) if _session_id else None,
        )
        if _memory.as_text:
            capabilities = (capabilities + "\n\n" + _memory.as_text) if capabilities else _memory.as_text
    except Exception as exc:
        logger.warning("semantic_planner.memory_planning_failed", error=str(exc)[:200])

    cache = get_parse_cache()

    start_ts = time.perf_counter()
    # A REPLAN (validator/compile errors present) must NEVER reuse the
    # rejected plan from the cache — the cached plan is exactly what the
    # deterministic validator just rejected, and re-serving it makes the
    # bounded repair loop burn its rounds on the identical plan (the
    # hallucinated-plan loop observed in the trace). Cache only the first
    # attempt of a query.
    _replanning = bool(snapshot.get("_plan_validator_errors") or
                       snapshot.get("_compile_errors"))
    if _replanning:
        logger.info(
            "semantic_planner.cache_bypassed_replan",
            query=last_message[:60],
        )
        cached = None
    else:
        # registry_checksum is included via _registry_fingerprint() inside cache
        cached = await cache.get(last_message, [], model, context=prior_chain)
    if cached is not None:
        elapsed = time.perf_counter() - start_ts
        logger.info(
            "semantic_planner.cache_hit",
            workflow=True,
            latency_ms=round(elapsed * 1000),
        )
        if isinstance(cached, dict) and "nodes" in cached:
            cached["nodes"] = _sanitize_ops(cached["nodes"], valid_ops)
            cached["nodes"] = _drop_unresolved(cached["nodes"], valid_ops)
            await _apply_strong_signal_correction(cached["nodes"], last_message)
            _drop_errs = _surface_cache_drops(cached)
            # A cached plan carrying schema-invalid input values (garbage the
            # model emitted once) is UNTRUSTWORTHY — treat it as a miss and
            # replan fresh (self-healing; never execute a known-bad plan).
            if _plan_unsafe_to_cache(cached["nodes"], last_message):
                logger.warning(
                    "semantic_planner.cache_schema_invalid_replan",
                    query=last_message[:60],
                )
                cached = None
            else:
                # P0-B: cached plans also pass the DETERMINISTIC binder (L1-L4
                # only — never an LLM call on the cache-hit path). Pre-P0-B
                # cache entries gain their bindings here; already-bound plans
                # are no-ops.
                _cached_report: dict[str, Any] | None = None
                try:
                    from nexus.compiler.binder import bind_parameters  # noqa: PLC0415

                    _cached_report = (
                        await bind_parameters(cached["nodes"], last_message)
                    ).model_dump()
                except Exception as _cexc:
                    logger.warning("semantic_planner.cache_binding_failed", error=str(_cexc)[:150])
                # Cache-hit plans still emit PlanningCompleted (the benchmark
                # evidence layer and downstream observability read the planned
                # DAG regardless of cache origin — a hit without the event
                # scores planned={} despite correct execution).
                await emit_planning_completed(
                    session_id=snapshot.get("session_id", ""),
                    workflow=cached,
                    planner_confidence=min(0.95, 0.5 + (len(cached.get("nodes") or []) * 0.1)),
                    detected_intents=(
                        _detected_intents_payload(intent_graph) if intent_graph is not None else None
                    ),
                )
                return _build_patch(cached, cached=True, latency_ms=round(elapsed * 1000), version=ctx.version + 1,
                                    errors=[f"SemanticPlanner: could not resolve capabilities: {', '.join(_drop_errs[:5])}"] if _drop_errs else None,
                                    binding_report=_cached_report)
        if cached is not None and isinstance(cached, list):
            cached = {"version": "1.0", "nodes": _sanitize_ops(cached, valid_ops), "collections": {}}
            cached["nodes"] = _drop_unresolved(cached["nodes"], valid_ops)
            await _apply_strong_signal_correction(cached["nodes"], last_message)
            _drop_errs = _surface_cache_drops(cached)
            if _plan_unsafe_to_cache(cached["nodes"], last_message):
                logger.warning(
                    "semantic_planner.cache_schema_invalid_replan",
                    query=last_message[:60],
                )
                cached = None
            else:
                # P0-B deterministic binding on the cache-hit path (see above).
                _cached_report: dict[str, Any] | None = None
                try:
                    from nexus.compiler.binder import bind_parameters  # noqa: PLC0415

                    _cached_report = (
                        await bind_parameters(cached["nodes"], last_message)
                    ).model_dump()
                except Exception as _cexc:
                    logger.warning("semantic_planner.cache_binding_failed", error=str(_cexc)[:150])
                await emit_planning_completed(
                    session_id=snapshot.get("session_id", ""),
                    workflow=cached,
                    planner_confidence=min(0.95, 0.5 + (len(cached.get("nodes") or []) * 0.1)),
                    detected_intents=(
                        _detected_intents_payload(intent_graph) if intent_graph is not None else None
                    ),
                )
                return _build_patch(cached, cached=True, latency_ms=round(elapsed * 1000), version=ctx.version + 1,
                                    errors=[f"SemanticPlanner: could not resolve capabilities: {', '.join(_drop_errs[:5])}"] if _drop_errs else None,
                                    binding_report=_cached_report)
    # cached None (miss or schema-invalid replay) → fresh planning below

    from nexus.agent.prompts.manager import prompt_manager as _pm
    settings = get_settings().agent

    # HYBRID/CHECKPOINT SCOPE: when planning a dynamic workflow step or a
    # modified approval, the planner must see ONLY that intent — passing the
    # full conversation history makes the LLM re-plan earlier steps and
    # hallucinate unrelated tools (observed in production runs).
    history_str = history_for_plan
    # Fail-closed prompt resolution (I9): only registered versions may be
    # served; a missing prompt is a typed configuration error
    # (PromptVersionError) that must surface, never a silent fallback.
    prompt = _pm.render(
        "logical_planner", "2.4",
        capabilities=capabilities if capabilities else "(none available)",
        history=history_str if history_str else "(no prior conversation)",
    )

    total_cost: float = 0.0
    total_tokens: int = 0
    parsed: dict[str, Any] | None = None

    # A1/P1-A: RESERVE-BEFORE-START — every planner LLM call (instructor,
    # JSON fallback, repair) draws from the invocation budget BEFORE it
    # begins; an exhausted llm-call dimension terminates planning with an
    # explicit error, never a silent overspend.
    from nexus.agent.budget import budget_from_state as _budget_from_state

    _bud = _budget_from_state(snapshot)

    # P2-A PRE-CHECK: MEGA-INTENT REQUESTS go STRAIGHT to hierarchical
    # (chunked) planning — a single structured extraction over 20+ intent
    # units is the T132/U133/W135/S126 ``got []`` class (the model cannot
    # emit a very large workflow in one pass; the doomed single-shot costs
    # 60-90s+ then still fails). Chunked planning asks for a SMALL plan
    # per dependency-ordered chunk and merges. Normal requests (<= the
    # threshold) keep the existing single-shot path unchanged.
    _mega_units: list[str] = []
    try:
        if intent_graph is not None:
            _mega_units = [i.goal for i in intent_graph.executable]
    except Exception:
        _mega_units = []
    try:
        _max_single = int(get_settings().compiler.max_single_pass_intents)
    except Exception:
        _max_single = 12
    if len(_mega_units) > _max_single:
        logger.warning(
            "semantic_planner.chunked_direct",
            units=len(_mega_units),
            threshold=_max_single,
        )
        _rel = []
        try:
            if intent_graph is not None:
                _rel = list(intent_graph.relationships)
        except Exception:
            _rel = []
        _chunked = await _chunked_plan_extract(
            llm, model, last_message, _mega_units,
            capabilities, valid_ops, settings, _bud,
            relationships=_rel,
        )
        if _chunked is not None:
            parsed = _chunked
            logger.info(
                "semantic_planner.chunked_merged_direct",
                nodes=len(_chunked.get("nodes") or []),
                ops=[n.get("op") for n in _chunked.get("nodes") or []],
            )

    # Try instructor first with strict Literal enforcement; on a typed LLM
    # failure (provider timeout/5xx — flaky shared endpoints), retry before
    # surfacing an honest error: transient provider failures are common and a
    # re-attempt materially improves availability.
    for _retry in range(3):
        if parsed is not None:
            break  # P2-A: chunked planning already produced a merged plan
        if not _bud.consume("llm_calls"):
            return _build_error_patch(
                Exception("invocation llm-call budget exhausted during planning"),
                total_tokens,
                total_cost,
                version=ctx.version + 1,
                invocation_budget=_bud.to_dict(),
            )
        parsed = await _instructor_extract(prompt, last_message, llm, model, settings, valid_ops)
        if parsed is not None:
            break
        logger.info("semantic_planner.fallback_json_extract")
        if not _bud.consume("llm_calls"):
            return _build_error_patch(
                Exception("invocation llm-call budget exhausted during planning"),
                total_tokens,
                total_cost,
                version=ctx.version + 1,
                invocation_budget=_bud.to_dict(),
            )
        parsed = await _json_extract(prompt, last_message, llm, model, settings)
        if parsed is not None:
            break
        logger.warning(
            "semantic_planner.extraction_failed_retry",
            attempt=_retry + 1,
        )

    # P1-C DIAGNOSED RECOVERY: the 3-attempt loop exhausted — classify the
    # failure and apply ONE cheap, class-appropriate repair. EMPTY_PLAN is
    # the dominant nano class (the "got []" benchmark signature): the model
    # returned a VALID ``{"nodes": []}`` while executable intent units
    # exist — a single constrained repair prompt re-plans them. Anything
    # else surfaces as PLANNING_FAILED (never a silent empty plan).
    if parsed is not None and (
        not isinstance(parsed.get("nodes"), list) or not parsed.get("nodes")
    ):
        _diagnosis = _diagnose_plan_failure(parsed, "", [])
        _executable_units = []
        try:
            if intent_graph is not None:
                _executable_units = [i.goal for i in intent_graph.executable]
        except Exception:
            _executable_units = []
        if _diagnosis == _PLAN_FAILURE_EMPTY and _executable_units:
            logger.warning(
                "semantic_planner.empty_plan_repair",
                units=len(_executable_units),
            )
            repaired = await _repair_empty_plan(
                llm, model, last_message, _executable_units,
                capabilities, valid_ops, _bud,
            )
            if repaired is not None:
                parsed = repaired
            else:
                # P2-A HIERARCHICAL MEGA-DAG PLANNING: the empty-plan
                # repair failed — this is the 20+ intent class (T132/U133/
                # W135/S126) where a SINGLE structured extraction over the
                # whole request fails. Chunk the intent units and plan per
                # chunk (each small extraction succeeds), then merge.
                try:
                    _max_single = int(get_settings().compiler.max_single_pass_intents)
                except Exception:
                    _max_single = 12
                if len(_executable_units) > _max_single:
                    logger.warning(
                        "semantic_planner.chunked_planning",
                        units=len(_executable_units),
                    )
                    _rel = []
                    try:
                        if intent_graph is not None:
                            _rel = list(intent_graph.relationships)
                    except Exception:
                        _rel = []
                    chunked = await _chunked_plan_extract(
                        llm, model, last_message, _executable_units,
                        capabilities, valid_ops, settings, _bud,
                        relationships=_rel,
                    )
                    if chunked is not None:
                        parsed = chunked
                        logger.info(
                            "semantic_planner.chunked_merged",
                            nodes=len(chunked.get("nodes") or []),
                            chunks=(
                                len(_executable_units) + 5
                            ) // max(1, int(get_settings().compiler.chunk_size)),
                        )

    if parsed is None:
        return _build_error_patch(
            Exception("All extraction methods failed"),
            total_tokens,
            total_cost,
            version=ctx.version + 1,
        )

    nodes = parsed.get("nodes", [])
    if not isinstance(nodes, list):
        nodes = []
    parsed["nodes"] = nodes[:_SP_MAX_NODES]

    # Planner-level errors surfaced on the state patch (kept OUT of the
    # strict LogicalWorkflow dict which forbids extra keys).
    planner_errors: list[str] = []
    # P2-A.2: map-degradation ledger (dangling iterate_over stripped to a
    # single body) — surfaced so a lost fan-out is never invisible.
    _planner_map_degradations: list[dict[str, Any]] = []

    # SANITIZE OPS: layered deterministic resolution (exact → domain →
    # alias → RapidFuzz ≥ threshold). Unresolvable ops are collected for
    # LLM repair (top-K, last resort) — never silently dropped.
    parsed["nodes"] = _sanitize_ops(parsed["nodes"], valid_ops, domain_hint=domain_hint)

    unresolved_ops: list[str] = []
    for node in parsed["nodes"]:
        if isinstance(node, dict):
            unresolved_ops.extend(node.pop("_unresolved_ops", []))
    if unresolved_ops:
        from nexus.config.settings import get_settings as _sp_settings

        repair_enabled = True
        try:
            repair_enabled = _sp_settings().resolver.enable_llm_repair
        except Exception:
            repair_enabled = True
        if repair_enabled and valid_ops:
            if _bud.consume("llm_calls"):
                repair_map = await _repair_ops(llm, model, unresolved_ops, valid_ops)
            for node in parsed["nodes"]:
                if not isinstance(node, dict):
                    continue
                op = str(node.get("op") or "")
                if op in repair_map:
                    logger.info(
                        "semantic_planner.op_repaired",
                        requested=op,
                        resolved=repair_map[op],
                    )
                    node["op"] = repair_map[op]

        # Deterministic strong-signal correction: when the ResolutionEngine's
        # TOP candidate matched via an OPERATOR-DECLARED signal (exact alias /
        # example containment / keyword) with a dominant score (>= 2x the next
        # candidate), and the LLM plan omitted it entirely, correct the first
        # op to the engine's pick. Declared metadata outranks the LLM's guess —
        # fully engine-driven, no hardcoded names.
        await _apply_strong_signal_correction(parsed.get("nodes") or [], last_message)

        # NEVER execute unresolved ops: drop them from the plan and surface
        # an explicit error (refinement: no guessing, no silent failure).
        surviving: list[dict[str, Any]] = []
        dropped: list[str] = []
        for node in parsed["nodes"]:
            if not isinstance(node, dict):
                surviving.append(node)
                continue
            op = str(node.get("op") or "")
            if op in valid_ops:
                surviving.append(node)
            else:
                dropped.append(op)
        parsed["nodes"] = surviving
        if dropped:
            # Errors live OUTSIDE the strict LogicalWorkflow dict — attach to
            # the state patch so they surface without breaking IR validation.
            planner_errors = [
                f"SemanticPlanner: could not resolve capabilities: {', '.join(dropped[:5])}"
            ]
            logger.warning(
                "semantic_planner.ops_dropped",
                dropped=dropped,
                count=len(dropped),
            )

    elapsed = time.perf_counter() - start_ts

    # P0-B PARAMETER + PROVENANCE BINDING: deterministically resolve WHERE
    # every required input comes from — user value, artifact-output from a
    # planned producer (placeholder + dependency edge), or (fresh-planning
    # only, budget-guarded) a single LLM extraction. The plan is mutated in
    # place so the bound inputs are what the validator sees and the cache
    # stores. Missing inputs become explicit MissingInput states — the
    # validator classifies them instead of a bare "missing inputs" error.
    binding_report: dict[str, Any] | None = None
    try:
        from nexus.compiler.binder import bind_parameters  # noqa: PLC0415

        report = await bind_parameters(
            nodes,
            last_message,
            llm=llm,
            model=model,
            budget=_bud,
            allow_llm=bool(
                snapshot.get("_force_query_type")
                or str(snapshot.get("_query_type") or "") != "conversational"
            ),
        )
        binding_report = report.model_dump()
        logger.info(
            "semantic_planner.binding_report",
            query=last_message[:60],
            bound=len(report.bindings),
            missing=len(report.missing),
            states=[m.state for m in report.missing],
        )
    except Exception as _bind_exc:
        logger.warning("semantic_planner.binding_failed", error=str(_bind_exc)[:200])

    # P1-D MAP COLLAPSE (post-binding, pre-cache): independent same-
    # capability entity instances become ONE Map node + a declared
    # collection (the reviewer's fan-out abstraction). The bound inputs
    # are final here, so the collapse is deterministic and the cached plan
    # carries the canonical representation.
    try:
        _map_nodes, _map_collections = _collapse_map_candidates(nodes)
        if _map_collections:
            parsed["nodes"] = _map_nodes
            parsed.setdefault("collections", {}).update(_map_collections)
            nodes = _map_nodes
            logger.info(
                "semantic_planner.map_collapse",
                maps=list(_map_collections.keys()),
                cardinalities=[len(v) for v in _map_collections.values()],
                nodes_after=len(nodes),
            )
        # P2-A.2 COLLECTIONS PERSISTENCE INVARIANT: every ``iterate_over``
        # ref must have a declared collection — a dangling map node (from a
        # chunked merge or a replan boundary where collections were lost)
        # would fail validation with ``unresolved_iterate_over`` and burn a
        # replan cycle. Strip the iterate_over from any node whose
        # collection is absent (the node degrades to a single body
        # execution — never a dangling map).
        _wf_collections = parsed.get("collections") if isinstance(parsed, dict) else {}
        nodes, _map_degradations = _strip_dangling_maps(nodes, _wf_collections)
        parsed["nodes"] = nodes
        if _map_degradations:
            _planner_map_degradations = _map_degradations
    except Exception as _map_exc:
        logger.warning("semantic_planner.map_collapse_failed", error=str(_map_exc)[:150])

    # NEVER CACHE A STRUCTURALLY INVALID PLAN (D0/P0-C, I11): schema-invalid
    # input values AND invented input keys are statically detectable — a
    # plan carrying either would be replayed forever from the cache and
    # fail at execution or send junk parameters. Provenance/alignment are
    # message-dependent and stay validator-side (the validator runs after
    # every cache-hit planning too, so they still gate execution).
    if not _plan_unsafe_to_cache(nodes, last_message):
        await cache.set(last_message, [], model, nodes, context=prior_chain)
    else:
        logger.warning(
            "semantic_planner.skip_cache_structurally_invalid",
            query=last_message[:60],
        )

    # Emit PlanningCompleted event with confidence derived from node count
    session_id = snapshot.get("session_id", "")
    plan_confidence = min(0.95, 0.5 + (len(nodes) * 0.1)) if nodes else 0.0
    _intent_payload = None
    if intent_graph is not None:
        try:
            _intent_payload = {
                "intents": intent_graph.as_dicts(),
                "relationships": intent_graph.relationships_as_dicts(),
                "source": intent_graph.source,
            }
        except Exception:
            _intent_payload = None
    await emit_planning_completed(
        session_id=session_id,
        workflow=parsed,
        planner_confidence=plan_confidence,
        detected_intents=_intent_payload,
    )

    logger.info(
        "semantic_planner.complete",
        node_count=len(nodes),
        ops=[n.get("op") for n in nodes if isinstance(n, dict)],
        cached=False,
        latency_ms=round(elapsed * 1000),
    )

    # A1/P1-A: the RESERVED ledger (built before the first call) flows back
    # on the patch — the runner merges it into its own budget.
    return _build_patch(
        parsed,
        total_tokens=total_tokens,
        cost_usd=total_cost,
        latency_ms=round(elapsed * 1000),
        version=ctx.version + 1,
        errors=planner_errors or None,
        budget_exceeded=_budget_flag("planning", elapsed * 1000),
        invocation_budget=_bud.to_dict(),
        binding_report=binding_report,
        intent_graph=intent_graph,
        map_degradations=_planner_map_degradations or None,
    )


def _strip_dangling_maps(
    nodes: list[dict[str, Any]],
    collections: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """P2-A.2 collections-persistence guard: every ``iterate_over`` ref
    must have a declared collection. A dangling map node (collections lost
    across a replan/chunked-merge boundary) degrades to a single body
    execution — never a validation-failing map.

    Returns ``(pruned_nodes, degradations)`` where each degradation is
    ``{"node": ref, "iterate_over": key, "reason": "missing collection"}``
    — the caller surfaces it so a lost fan-out is NEVER indistinguishable
    from successful map execution (the reviewer's instrumentation).
    """
    if not isinstance(collections, dict):
        collections = {}
    pruned: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    for n in nodes:
        if not isinstance(n, dict):
            pruned.append(n)
            continue
        _io = n.get("iterate_over")
        if _io and str(_io) not in collections:
            logger.warning(
                "semantic_planner.strip_dangling_map",
                node=n.get("ref"),
                iterate_over=str(_io),
            )
            n = dict(n)
            n.pop("iterate_over", None)
            degradations.append({
                "node": str(n.get("ref") or "?"),
                "iterate_over": str(_io),
                "reason": "missing collection (replan/merge boundary)",
            })
        pruned.append(n)
    return pruned, degradations


def _collapse_map_candidates(
    nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[Any]]]:
    """P1-D MAP COLLAPSE (deterministic, post-binding): independent same-
    capability entity instances → ONE Map node + a declared collection.

    The reviewer's D48 abstraction: "one capability + multiple entity
    instances + map-compatible operation" compiles to a Map/fan-out rather
    than N unrelated planner decisions. Conditions (all deterministic,
    metadata-free):

    - at least 2 nodes with the SAME ``op``;
    - identical ``depends_on`` (independent leaves — never collapse nodes
      with differing dependencies);
    - identical inputs EXCEPT exactly one string value (the entity
      parameter — chicken/pasta/rice for search_meals);
    - the varying values are the collection items.

    Returns ``(collapsed_nodes, new_collections)``. Nodes that do not
    satisfy every condition are passed through untouched.
    """
    if not nodes or len(nodes) < 2:
        return nodes, {}
    collapsed: list[dict[str, Any]] = []
    consumed: set[int] = set()
    collections: dict[str, list[Any]] = {}
    seen: dict[tuple[str, tuple, frozenset], list[int]] = {}
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        op = str(node.get("op") or "")
        if not op:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        deps = tuple(sorted(str(d) for d in (node.get("depends_on") or [])))
        key = (op, deps, frozenset(inputs.keys()))
        seen.setdefault(key, []).append(i)
    for key, idxs in seen.items():
        if len(idxs) < 2:
            continue
        op, deps, _ = key
        group = [nodes[i] for i in idxs]
        varying: str | None = None
        values: list[Any] = []
        ok = True
        for param in (group[0].get("inputs") or {}):
            vals = [str((n.get("inputs") or {}).get(param, "")) for n in group]
            if len(set(vals)) == 1:
                continue
            if varying is not None:
                ok = False  # more than one varying param — not a map
                break
            varying = param
            values = [(n.get("inputs") or {}).get(param) for n in group]
        if not ok or varying is None or len(values) < 2:
            continue
        # Map-compatible: all varying values are distinct scalar strings.
        if len({str(v) for v in values}) != len(values):
            continue
        if not all(isinstance(v, str) and v.strip() for v in values):
            continue
        # Build the Map node: identical inputs with the varying param
        # replaced by the ${item} placeholder.
        base_inputs = dict(group[0].get("inputs") or {})
        base_inputs[varying] = "${item}"
        map_node = {
            "op": op,
            "ref": str(group[0].get("ref") or f"{op}_map"),
            "inputs": base_inputs,
            "depends_on": list(deps),
            "iterate_over": f"{op}_items",
        }
        collections[f"{op}_items"] = values
        collapsed.append(map_node)
        consumed.update(idxs)
    surviving = [
        node for i, node in enumerate(nodes)
        if i not in consumed
    ]
    surviving.extend(collapsed)
    return surviving, collections


def _detected_intents_payload(intent_graph: Any) -> dict[str, Any] | None:
    """P0-C: serialize the structured intent graph for the planning event
    (the benchmark's requested-vs-planned intent accounting)."""
    try:
        return {
            "intents": intent_graph.as_dicts(),
            "relationships": intent_graph.relationships_as_dicts(),
            "source": intent_graph.source,
        }
    except Exception:
        return None


def _budget_flag(stage: str, elapsed_ms: float) -> str | None:
    """ExecutionBudget degradation flag (metadata-driven thresholds).

    Returns the stage name when the stage exceeded its configured budget —
    the routing/synthesis layers then degrade (lightweight pipeline /
    deterministic renderer) instead of burning more latency.
    """
    try:
        from nexus.config.settings import get_settings

        budget = getattr(get_settings().compiler, f"{stage}_budget_ms", 0)
    except Exception:
        budget = 0
    if budget > 0 and elapsed_ms > budget:
        return stage
    return None


def _build_patch(
    workflow: dict,
    cached: bool = False,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
    version: int = 1,
    errors: list[str] | None = None,
    budget_exceeded: str | None = None,
    invocation_budget: dict | None = None,
    binding_report: dict[str, Any] | None = None,
    intent_graph: Any = None,
    map_degradations: list[dict[str, Any]] | None = None,
) -> StatePatch:
    """Build a StatePatch with the LogicalWorkflow and metadata.

    Args:
        workflow: The LogicalWorkflow dict (strict — no extra keys).
        cached: Whether this came from the plan cache.
        total_tokens: LLM token usage.
        cost_usd: LLM cost.
        latency_ms: Planning latency.
        version: Target context version.
        errors: Optional planner errors surfaced on the state patch.
        invocation_budget: The ReasoningBudget ledger (consumed LLM calls).
        binding_report: P0-B provenance ledger (parameter bindings + missing
            inputs classified explicitly).
    """
    updates: dict[str, Any] = {
        "_logical_workflow": workflow,
        "_extraction_result": {
            "node_count": len(workflow.get("nodes", [])),
            "cached": cached,
        },
    }

    if budget_exceeded:
        updates["_budget_exceeded"] = budget_exceeded

    if errors:
        updates["errors"] = errors

    if invocation_budget:
        updates["_invocation_budget"] = invocation_budget

    if binding_report:
        updates["_binding_report"] = binding_report

    if map_degradations:
        updates["_map_degradations"] = map_degradations

    if intent_graph is not None:
        try:
            updates["_detected_intents"] = {
                "intents": intent_graph.as_dicts(),
                "relationships": intent_graph.relationships_as_dicts(),
                "source": intent_graph.source,
            }
        except Exception:
            pass

    if total_tokens:
        updates["_total_tokens"] = total_tokens
        updates["_cost_breakdown"] = {"semantic_planner": cost_usd}
        updates["total_cost_usd"] = cost_usd

    return StatePatch(version=version, updates=updates, ir_stack_update=None)


def _build_error_patch(
    exc: Exception,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
    version: int = 1,
    invocation_budget: dict | None = None,
) -> StatePatch:
    """Build error StatePatch when LLM call fails."""
    patch = _build_patch(
        {"version": "1.0", "nodes": [], "collections": {}},
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        version=version,
        invocation_budget=invocation_budget,
    )
    patch.updates["errors"] = [f"SemanticPlanner: LLM call failed — {exc}"]
    return patch


