"""Deterministic Parameter + Provenance Binder (P0-B).

Separates ``intent → capability`` from ``capability → arguments`` from
``argument → provenance``.  The LLM proposes semantic values; this binder
deterministically decides WHERE each required input comes from, through a
layered pipeline — never asks the LLM to invent missing required parameters.

Layers (each layer is metadata-driven, zero hardcoded domain logic):

- **L1 — direct user value**: the planner already emitted a non-empty input.
  Provenance is recorded as ``user``.
- **L2 — artifact-output matching**: a planned node's required input is
  supplied by ANOTHER planned node that produces that artifact (registry
  ``produces``/``consumes`` metadata).  The input is rewritten to a
  ``${producer_ref.result.field}`` placeholder (resolved at execution by the
  executor's placeholder machinery) and the dependency edge is added.
- **L3 — semantic compatibility**: producer candidates are matched via the
  registry metadata (``produces`` list), which is the semantic contract.
- **L4 — type compatibility**: a candidate is rejected when the consumer's
  declared JSON-Schema type can never accept the produced value (declared
  types only; silent metadata is trusted, never guessed).
- **L5 — LLM extraction fallback**: a single bounded, strict-JSON call for
  the parameters that remain unbound after L1–L4 — and only when the query
  plausibly contains the value.  Budget-guarded; off for cache-hit paths.

Entity identity (multi-producer cases, B3/B4): when several planned nodes
could supply the artifact, the producer whose OWN inputs share the
consumer's entity values is preferred (deterministic overlap scoring —
``geocode(Lahore)`` feeds ``weather(Lahore)``, never the Tokyo one).

Every decision is recorded in a :class:`BindingReport` with explicit states:

``BOUND / MISSING / AMBIGUOUS / INVALID``
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

logger = structlog.get_logger("nexus.compiler.binder")
_ENTITY_WORDS_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9._/-]{2,}")


class ParameterBinding(BaseModel):
    """A single bound input parameter with its provenance."""

    model_config = ConfigDict(extra="forbid")

    target_node: str = Field(description="Node ref whose input was bound")
    target_parameter: str = Field(description="Input parameter name")
    source_type: str = Field(
        description="Where the value comes from: user | artifact | node_output | derived | default | llm"
    )
    source_node: str | None = Field(default=None, description="Producer node ref (node_output/artifact)")
    source_path: str | None = Field(default=None, description="Field path on the source (e.g. 'result.latitude')")
    confidence: float | None = Field(default=None, description="Binding confidence (0-1)")
    note: str = Field(default="", description="Human-readable provenance note")


class MissingInput(BaseModel):
    """A required input with no resolvable source — explicit, not ``None``."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(description="Node ref with the missing input")
    parameter: str = Field(description="Required parameter name")
    state: str = Field(description="MISSING | AMBIGUOUS | INVALID")
    reason: str = Field(description="Why the input could not be bound")
    candidate_sources: list[str] = Field(default_factory=list, description="Candidate producers examined")
    clarification_required: bool = Field(default=False, description="True when the user must supply the value")


class BindingReport(BaseModel):
    """Full provenance ledger for one planning pass."""

    model_config = ConfigDict(extra="forbid")

    bindings: list[ParameterBinding] = Field(default_factory=list)
    missing: list[MissingInput] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Compact diagnostic summary (benchmark-friendly)."""
        bound = len(self.bindings)
        return {
            "bound_required_params": bound,
            "missing_required_params": len(self.missing),
            "provenance_valid_params": bound,
            "missing_states": {m.parameter: m.state for m in self.missing},
        }


def _meta(op: str) -> dict[str, Any]:
    """Capability metadata from the GlobalContext index (metadata-driven)."""
    try:
        from nexus.context.global_context import get_global_context

        index = getattr(get_global_context(), "capability_index", {}) or {}
    except Exception:
        index = {}
    return index.get(op) or {}


def _produced_artifact_names(producer_op: str, consumer_param: str) -> list[str]:
    """Names the producer could supply the consumer's parameter under.

    Matches the producer's ``produces`` list against the consumer's
    parameter name AND its declared ``x-aliases``.  Returns the produced
    artifact names (empty = no semantic match).
    """
    meta = _meta(producer_op)
    produces = [str(p) for p in (meta.get("produces") or [])]
    if not produces:
        return []
    aliases: list[str] = [consumer_param.lower()]
    in_aliases = meta.get("input_aliases") or {}
    if isinstance(in_aliases, dict):
        aliases.extend(str(a).lower() for a in (in_aliases.get(consumer_param) or []))
    return [p for p in produces if p.lower() in aliases]


def _type_compatible(consumer_op: str, consumer_param: str, producer_op: str) -> bool:
    """L4 type guard: reject a producer when the declared JSON-Schema types
    can never meet.  No declared types -> trust the semantic produces list."""
    consumer_meta = _meta(consumer_op)
    in_schema = consumer_meta.get("input_schema") or {}
    props = (in_schema.get("properties") or {}) if isinstance(in_schema, dict) else {}
    c_type = (props.get(consumer_param) or {}).get("type") if isinstance(props, dict) else None
    if not c_type or c_type not in ("string", "number", "integer", "boolean"):
        return True
    producer_meta = _meta(producer_op)
    out_schema = producer_meta.get("output_schema") or {}
    out_props = (out_schema.get("properties") or {}) if isinstance(out_schema, dict) else {}
    p_types = {
        (p.get("type") or "") for p in out_props.values()
        if isinstance(p, dict)
    } if isinstance(out_props, dict) else set()
    if not p_types:
        return True
    if c_type == "number" and "number" in p_types:
        return True
    if c_type == "integer" and p_types & {"integer", "number"}:
        return True
    return c_type in p_types


_CAMEL_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)")


def _ref_words(ref: str) -> set[str]:
    """Entity words from a node ref label (camelCase-aware, lowercased)."""
    words: set[str] = set()
    for piece in re.split(r"[^a-zA-Z0-9]+", ref or ""):
        for w in _CAMEL_RE.findall(piece):
            if len(w) >= 2:
                words.add(w.lower())
    return words


def _entity_overlap(a: dict[str, Any], b: dict[str, Any]) -> int:
    """Deterministic entity-overlap score between two nodes.

    Scores both the input VALUES and the REF LABELS (the planner's own
    entity labels — ``wTokyo`` ↔ ``g2(query=Tokyo)`` share "tokyo") so a
    consumer without inputs still binds to its own producer (B3/B4).
    """
    def tokens(d: dict[str, Any], ref: str) -> set[str]:
        out: set[str] = set()
        for v in (d or {}).values():
            if isinstance(v, str) and v:
                out.update(_ENTITY_WORDS_RE.findall(v.lower()))
            elif isinstance(v, (int, float)):
                out.add(str(v))
        out |= _ref_words(ref)
        return out

    a_t = tokens(a.get("inputs") or {}, str(a.get("ref") or ""))
    b_t = tokens(b.get("inputs") or {}, str(b.get("ref") or ""))
    if not a_t or not b_t:
        return 0
    return len(a_t & b_t)


def _pick_producer(
    consumer: dict[str, Any],
    candidates: list[dict[str, Any]],
    consumer_param: str,
    position: int = 0,
    reuse_allowed: bool = False,
) -> dict[str, Any] | None:
    """Entity-identity selection among multiple producer candidates.

    Prefers the producer whose ref/input entities overlap the consumer's
    (B3/B4 — never reuse one location for another).  When NO candidate
    carries a distinguishing entity (generic ``wA``/``gA`` labels), the
    tie resolves POSITIONALLY — the i-th consumer binds the i-th producer
    in plan order (deterministic identity preservation for parallel A/B
    pairs).

    Args:
        consumer: The node consuming the artifact.
        candidates: Producer node candidates.
        consumer_param: The required parameter being bound.
        position: How many consumers have already bound this param.
        reuse_allowed: True when every candidate shares ONE entity that the
            user query names (legitimate reuse — the P108 "weather in Lahore
            twice" class). False → returning None signals AMBIGUOUS.

    Returns:
        The selected producer, or ``None`` when pairing would silently
        reuse a producer without a legitimate entity signal (AMBIGUOUS).
    """
    scored = sorted(
        candidates,
        key=lambda c: _entity_overlap(consumer, c),
        reverse=True,
    )
    if not scored:
        return None
    if len(scored) == 1:
        if position > 0 and _entity_overlap(consumer, scored[0]) == 0 and not reuse_allowed:
            # The only candidate was already claimed by an earlier consumer
            # and this consumer carries no entity signal — pairing would
            # silently REUSE it (the B3 class). None signals AMBIGUOUS.
            return None
        return scored[0]
    best = _entity_overlap(consumer, scored[0])
    if best > 0 and _entity_overlap(consumer, scored[1]) < best:
        return scored[0]
    # Entity-tie (or no signal). Positional pairing is safe ONLY while
    # distinct producers remain; once consumers outnumber producers with no
    # distinguishing entity, pairing would REUSE a producer (the B3 class —
    # one location silently reused for another). None signals AMBIGUOUS.
    if position >= len(scored) and not reuse_allowed:
        return None
    return scored[position % len(scored)]

def _bind_from_producer(node: dict[str, Any], producer: dict[str, Any], param: str, artifact: str) -> ParameterBinding:
    """Rewrite the consumer's input to a placeholder + record provenance."""
    node_ref = str(node.get("ref") or node.get("op") or "?")
    producer_ref = str(producer.get("ref") or producer.get("op") or "?")
    placeholder = f"${{{producer_ref}.result.{artifact}}}"
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        inputs = {}
        node["inputs"] = inputs
    inputs[param] = placeholder
    deps = node.get("depends_on")
    if not isinstance(deps, list):
        deps = []
        node["depends_on"] = deps
    if producer_ref not in deps:
        deps.append(producer_ref)
    return ParameterBinding(
        target_node=node_ref,
        target_parameter=param,
        source_type="node_output",
        source_node=producer_ref,
        source_path=f"result.{artifact}",
        confidence=0.95,
        note=f"{producer_ref}.result.{artifact} -> {node_ref}.{param} (artifact-output binding)",
    )


async def _llm_extract_missing(
    query: str,
    missing: list[dict[str, Any]],
    llm: Any,
    model: str,
    budget: Any,
) -> dict[str, Any]:
    """L5: single strict-JSON call for still-missing parameters.

    Args:
        query: The user message.
        missing: List of ``{"op", "ref", "parameter", "type"}`` entries.
        llm: The LLMClient.
        model: The model identifier.
        budget: The ReasoningBudget (consumes one ``llm_calls`` unit).

    Returns:
        A mapping of ``"ref:parameter" -> value``.  Empty on budget/LLM
        failure — the caller records MISSING, never a guessed value.
    """
    if not missing or llm is None:
        return {}
    try:
        if budget is not None and not budget.consume("llm_calls"):
            logger.warning("binder.llm_budget_exhausted")
            return {}
        keys = [f"{m['ref']}:{m['parameter']}" for m in missing]
        prompt = (
            "Extract parameter values from the user request.\n"
            "Rules:\n"
            "- Return ONLY a JSON object with these exact keys: "
            + ", ".join(f'"{k}"' for k in keys)
            + "\n"
            "- Each value must appear literally in the user request.\n"
            "- If a value is absent, omit that key.\n"
            "- Never invent, guess, translate, or compute values.\n"
            "User request: \"USER_REQUEST\"\n"
            "JSON:"
        ).replace("USER_REQUEST", query[:400])
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": "You are a strict JSON value extractor. Only output valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        if response.failed or not response.content:
            logger.warning("binder.llm_extract_failed", error=str(response.error)[:120])
            return {}
        content = str(response.content)
        logger.info("binder.llm_extract_raw", content=str(content)[:300])
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n```$", "", content)
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start:end + 1]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return {}
        # Only accept values that literally appear in the request (I2).
        q = query.lower()
        return {
            k: v for k, v in parsed.items()
            if isinstance(v, (str, int, float)) and not isinstance(v, bool)
            and (str(v).lower() in q or str(v) in q)
        }
    except Exception as exc:
        logger.warning("binder.llm_extract_error", error=str(exc)[:120])
        return {}


async def bind_parameters(
    nodes: list[dict[str, Any]],
    user_query: str,
    llm: Any = None,
    model: str = "",
    budget: Any = None,
    allow_llm: bool = False,
) -> BindingReport:
    """Deterministically bind every required input in the plan.

    Args:
        nodes: The planned logical nodes (mutated in place — inputs are
            rewritten to ``${...}`` placeholders and dependency edges added).
        user_query: The user's request (provenance + L5 extraction source).
        llm: Optional LLMClient for the L5 fallback.
        model: Model identifier for L5.
        budget: ReasoningBudget for L5 guarding.
        allow_llm: True only on the fresh-planning path (never cache hits).

    Returns:
        The :class:`BindingReport` — the full provenance ledger.
    """
    report = BindingReport()
    if not nodes:
        return report

    planned = [n for n in nodes if isinstance(n, dict)]
    if not planned:
        return report

    # Index planned nodes by ref for producer lookup (O(1)).
    by_ref: dict[str, dict[str, Any]] = {}
    for n in planned:
        r = str(n.get("ref") or "")
        if r:
            by_ref[r] = n

    # L5 candidates collected across the pass (batched into one call).
    l5_missing: list[dict[str, Any]] = []

    # B3/B4 identity: positional fallback counter per param — the i-th
    # consumer with no entity signal binds the i-th producer in plan order.
    positional: dict[str, int] = {}

    for node in planned:
        op = str(node.get("op") or "")
        if not op:
            continue
        meta = _meta(op)
        required = [str(r) for r in (meta.get("input_required") or [])]
        # P0-B L1 guard: a planner-provided value on an OPTIONAL param that
        # declares a schema DEFAULT is dropped — the deterministic default
        # outranks the LLM's guess (the ``namespace`` class: the planner
        # filled the repo name into a field that defaults to "library").
        # Metadata-driven (input_schema defaults); never hardcoded.
        in_schema = meta.get("input_schema") or {}
        schema_props = (in_schema.get("properties") or {}) if isinstance(in_schema, dict) else {}
        if isinstance(schema_props, dict) and schema_props:
            inputs = node.get("inputs")
            node_inputs = inputs if isinstance(inputs, dict) else {}
            for _k, _v in list(node_inputs.items()):
                if _k in required:
                    continue
                _prop = schema_props.get(_k)
                if isinstance(_prop, dict) and _prop.get("default") is not None:
                    logger.info(
                        "binder.drop_default_overridden",
                        node=node.get("ref"),
                        param=_k,
                        default=_prop.get("default"),
                        value=_v,
                    )
                    del node_inputs[_k]
        if not required:
            continue
        inputs = node.get("inputs")
        node_inputs = inputs if isinstance(inputs, dict) else {}
        provided = {
            k for k, v in node_inputs.items()
            if not (isinstance(v, str) and not v.strip())
        }
        for param in required:
            if param in provided:
                continue
            # L2/L3: producers already in the plan (artifact matching).
            producer_candidates: list[dict[str, Any]] = []
            for other in planned:
                if other is node:
                    continue
                other_op = str(other.get("op") or "")
                if not other_op:
                    continue
                if not _type_compatible(op, param, other_op):
                    continue
                if _produced_artifact_names(other_op, param):
                    producer_candidates.append(other)
            if producer_candidates:
                pos = positional.get(param, 0)
                # Legitimate-reuse signal (P108 class): all candidates share
                # ONE entity value that the user query literally names —
                # binding several consumers to it is correct, not reuse.
                q = (user_query or "").lower()
                cand_entities = {
                    str(v).lower()
                    for c in producer_candidates
                    for v in ((c.get("inputs") or {}).values() or [])
                    if isinstance(v, str) and v.strip() and v.lower() in q
                }
                reuse_allowed = len(cand_entities) == 1
                producer = _pick_producer(
                    node, producer_candidates, param,
                    position=pos, reuse_allowed=reuse_allowed,
                )
                positional[param] = pos + 1
                if producer is None:
                    # B3 AMBIGUOUS: consumers outnumber distinguishable
                    # producers — silent positional reuse would bind one
                    # location's artifacts to another consumer's inputs.
                    report.missing.append(MissingInput(
                        node_id=str(node.get("ref") or op),
                        parameter=param,
                        state="AMBIGUOUS",
                        reason=(
                            "multiple producer candidates with no distinguishing "
                            "entity signal and no distinct producer remaining"
                        ),
                        candidate_sources=[
                            str(p.get("op") or "?") for p in producer_candidates
                        ],
                        clarification_required=True,
                    ))
                    continue
                artifact = _produced_artifact_names(str(producer.get("op") or ""), param)[0]
                binding = _bind_from_producer(node, producer, param, artifact)
                report.bindings.append(binding)
                provided.add(param)
                continue

            # L4 registered-but-unplanned producer candidates (diagnostics).
            candidate_names: list[str] = []
            try:
                from nexus.context.global_context import get_global_context as _gc

                _index = getattr(_gc(), "capability_index", {}) or {}
                for _name, _m in _index.items():
                    if not isinstance(_m, dict):
                        continue
                    if param in (_m.get("produces") or []):
                        candidate_names.append(str(_name))
            except Exception:
                pass
            # L5: LLM extraction fallback (bounded, provenance-checked).
            if allow_llm and llm is not None and model:
                l5_missing.append({
                    "op": op,
                    "ref": str(node.get("ref") or op),
                    "parameter": param,
                    "type": (
                        (meta.get("input_schema") or {})
                        .get("properties", {}).get(param, {}).get("type")
                        if isinstance(meta.get("input_schema"), dict)
                        else None
                    ),
                })
                continue

            report.missing.append(MissingInput(
                node_id=str(node.get("ref") or op),
                parameter=param,
                state="MISSING",
                reason=f"required input has no resolvable source (layers L1-L4 exhausted)",
                candidate_sources=candidate_names,
                clarification_required=True,
            ))

    # L5 batch (fresh-planning path only).
    if l5_missing:
        values = await _llm_extract_missing(user_query, l5_missing, llm, model, budget)
        for m in l5_missing:
            key = f"{m['ref']}:{m['parameter']}"
            value = values.get(key)
            if value is None:
                # Also try the bare parameter key (model may omit the ref).
                value = values.get(m["parameter"])
            if value is None:
                report.missing.append(MissingInput(
                    node_id=m["ref"],
                    parameter=m["parameter"],
                    state="MISSING",
                    reason="no resolvable source after L1-L5; the user request carries no value",
                    candidate_sources=[],
                    clarification_required=True,
                ))
                continue
            node = by_ref.get(m["ref"])
            if node is None or not isinstance(node.get("inputs"), dict):
                continue
            node["inputs"][m["parameter"]] = value
            report.bindings.append(ParameterBinding(
                target_node=m["ref"],
                target_parameter=m["parameter"],
                source_type="llm",
                source_node=None,
                source_path=None,
                confidence=0.7,
                note="L5 LLM extraction (value traceable to the user request)",
            ))

    return report
