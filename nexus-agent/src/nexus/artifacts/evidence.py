"""P0-D EVIDENCE LAYER — the deterministic bridge between execution and synthesis.

Execution produces artifacts.  Synthesis must never discover what was
executed — the EVIDENCE COMPILER decides WHAT must be expressed
(deterministic), the LLM decides HOW (synthesis).

Pipeline:

    ArtifactGraph
        ↓  EvidenceCompiler (entity anchoring via logical-node inputs +
           producer chains; fact extraction via registry metadata)
        ↓
    ResponseEvidence[]  (entity-anchored, capability-labeled, fact-level)
        ↓  RequiredEvidenceCompiler (intent graph entities + requested
           outputs + registry produces)
        ↓
    Required evidence ⊆ available evidence  (GroundingValidator)
        ↓
    Nemotron synthesis (evidence packet, never the raw artifact graph)
        ↓
    Grounding gate: required entities/facts ⊆ rendered text
        ↓  FAIL → synthesis repair (one cheap call) → deterministic renderer

Entity identity reuses the P0-B identity logic (input-value overlap), so
Lahore ≠ Karachi everywhere in the evidence layer.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

logger = structlog.get_logger("nexus.artifacts.evidence")

_ENTITY_WORDS_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9._/-]{2,}")
_PLACEHOLDER_RE = re.compile(r"\$\{.*\}")


class EvidenceFact(BaseModel):

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Fact key (field name or flattened path)")
    value: Any = Field(description="Fact value")
    source_path: str = Field(description="Path into the artifact payload")
    semantic_type: str | None = Field(default=None, description="Declared type from output schema")
    user_relevant: bool = Field(default=True, description="True when the user likely wants this fact")


class ResponseEvidence(BaseModel):
    """Entity-anchored evidence for one executed capability."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Stable evidence identifier")
    artifact_id: str = Field(description="Source artifact id (uuid string)")
    entity_id: str | None = Field(default=None, description="Anchored entity (e.g. 'lahore')")
    entity_type: str | None = Field(default=None, description="Entity kind (location, repo, ...)")
    capability_id: str = Field(description="Capability that produced the artifact")
    operation: str = Field(description="The capability name (alias for capability_id)")
    facts: list[EvidenceFact] = Field(default_factory=list)
    source_node_id: str = Field(default="", description="Physical node id")
    confidence: float = Field(default=1.0, description="Evidence confidence")
    required_for_intent: str | None = Field(default=None, description="Intent this evidence serves")

    def fact_values(self) -> list[str]:
        """Non-trivial scalar values of this evidence (for text matching)."""
        out: list[str] = []
        for f in self.facts:
            v = f.value
            if isinstance(v, bool) or v is None:
                continue
            s = str(v).strip()
            if len(s) >= 2 and s.lower() != "none":
                out.append(s)
        return out


class EvidenceEntity(BaseModel):
    """Entity anchor for evidence grouping (P0-B identity reused)."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str = Field(description="Canonical lowercased id")
    canonical_name: str = Field(description="Display name (original casing)")
    entity_type: str = Field(default="entity", description="Entity kind")
    aliases: list[str] = Field(default_factory=list)


class GroundingCoverage(BaseModel):
    """Formal grounding invariant: required ⊆ available ⊆ rendered."""

    model_config = ConfigDict(extra="forbid")

    required_facts: int = Field(default=0)
    available_facts: int = Field(default=0)
    represented_facts: int = Field(default=0)
    coverage_ratio: float = Field(default=1.0)
    missing_evidence: list[str] = Field(default_factory=list)
    hallucinated_evidence: list[str] = Field(default_factory=list)
    required_entities_missing: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Grounding is complete only when every required entity and evidence
        item is represented AND no hallucinated values were detected (PH-2:
        hallucinated_evidence must affect the outcome, never just the log)."""
        return (
            self.coverage_ratio >= 0.999
            and not self.required_entities_missing
            and not self.hallucinated_evidence
        )


def _entity_from_inputs(inputs: dict[str, Any] | None, user_query: str = "") -> str | None:
    """Deterministic entity extraction from a node's input values.

    Values that literally appear in the user query are the entity (the
    P0-B provenance rule): geocode(query="Lahore") → "Lahore". Placeholders
    (``${...}``) and non-query values are not entities.
    """
    q = (user_query or "").lower()
    for v in (inputs or {}).values():
        if not isinstance(v, str) or not v.strip():
            continue
        if _PLACEHOLDER_RE.search(v):
            continue
        low = v.lower()
        if len(low) >= 2 and (not q or low in q):
            return v
    return None


def _logical_node_entity(node: dict[str, Any], user_query: str) -> str | None:
    """Entity of a logical workflow node: its own inputs first, then the
    producer chain (depends_on refs → their inputs). Deterministic."""
    ent = _entity_from_inputs(node.get("inputs"), user_query)
    if ent:
        return ent
    return None


class EvidenceCompiler:
    """ArtifactGraph → ResponseEvidence[] (deterministic, entity-anchored)."""

    def __init__(self) -> None:
        self._capability_meta: dict[str, dict[str, Any]] = {}

    def _meta(self, cap: str) -> dict[str, Any]:
        if not self._capability_meta:
            try:
                from nexus.context.global_context import get_global_context

                self._capability_meta = (
                    getattr(get_global_context(), "capability_index", {}) or {}
                )
            except Exception:
                self._capability_meta = {}
        return self._capability_meta.get(cap) or {}

    def compile(
        self,
        artifact_list: list[Any],
        user_query: str = "",
        workflow_nodes: list[dict[str, Any]] | None = None,
        physical_nodes: dict[str, Any] | None = None,
        collections: dict[str, list[Any]] | None = None,
    ) -> list[ResponseEvidence]:
        """Compile artifacts into entity-anchored evidence.

        Args:
            artifact_list: Registered artifacts (ArtifactBase instances).
            user_query: The user's request (entity provenance).
            workflow_nodes: Logical workflow nodes (ref → inputs/depends_on)
                — the entity source of truth.
            physical_nodes: Physical node map (id → inputs) for execution_id
                → logical-ref resolution.
            collections: P1-D declared MapNode iteration collections — a
                map-item artifact (``{nid}_item_{i}``) whose body iterates a
                collection is anchored to the COLLECTION ITEM (the entity
                — chicken/pasta/rice), not the `${item}` placeholder.

        Returns:
            Ordered ResponseEvidence list (one per artifact).
        """
        evidence: list[ResponseEvidence] = []
        if not artifact_list:
            return evidence

        # Logical ref → node dict (for entity + depends_on chain lookup).
        logical_by_ref: dict[str, dict[str, Any]] = {}
        for n in workflow_nodes or []:
            if isinstance(n, dict) and n.get("ref"):
                logical_by_ref[str(n["ref"])] = n

        # Physical id → logical ref (artifact.execution_id → node).
        phys_to_ref: dict[str, str] = {}
        for pid, pnode in (physical_nodes or {}).items():
            ref = ""
            if isinstance(pnode, dict):
                ref = str(pnode.get("symbolic_ref") or pnode.get("ref") or "")
            phys_to_ref[str(pid)] = ref

        # P1-D MAP-ITEM ANCHORING: MapNode ids resolve via their symbolic
        # ref (``{ref}_map``); item execution ids are ``{map_id}_item_{i}``.
        # The collection the map iterates holds the per-item ENTITY.
        collections = collections or {}
        map_ref_by_item_prefix: dict[str, tuple[str, list[Any]]] = {}
        for ref, node in logical_by_ref.items():
            io_key = node.get("iterate_over") if isinstance(node, dict) else None
            if not io_key:
                continue
            items = collections.get(str(io_key)) or []
            if items:
                map_ref_by_item_prefix[f"{ref}_map"] = (str(io_key), items)

        # Artifact → (entity, node) mapping, then chain-walk for entities.
        for i, art in enumerate(artifact_list):
            cap = str(getattr(art, "capability_id", "") or "")
            data = getattr(art, "data", None) or {}
            exec_id = str(getattr(art, "execution_id", "") or "")
            ref = phys_to_ref.get(exec_id, "")
            node = logical_by_ref.get(ref) or {}

            entity = _logical_node_entity(node, user_query)
            if entity is None:
                # P1-D: map-item artifact → the collection item IS the entity.
                _item_match = None
                for _prefix, (_key, _items) in map_ref_by_item_prefix.items():
                    if exec_id.startswith(f"{_prefix}_item_"):
                        _idx = exec_id.rsplit("_", 1)[-1]
                        if _idx.isdigit() and int(_idx) < len(_items):
                            _item_match = _items[int(_idx)]
                        break
                if _item_match is not None:
                    entity = str(_item_match)
                else:
                    # Walk the producer chain: depends_on refs → their inputs.
                    for dep in node.get("depends_on") or []:
                        dep_node = logical_by_ref.get(str(dep)) or {}
                        entity = _logical_node_entity(dep_node, user_query)
                        if entity:
                            break

            facts = self._extract_facts(cap, data)
            evidence.append(ResponseEvidence(
                evidence_id=f"ev_{i + 1}_{cap.replace('_', '')}",
                artifact_id=str(getattr(art, "artifact_id", "") or ""),
                entity_id=entity.lower() if entity else None,
                entity_type=self._entity_type(cap),
                capability_id=cap,
                operation=cap,
                facts=facts,
                source_node_id=exec_id,
                required_for_intent=None,
            ))
        return evidence

    def _entity_type(self, cap: str) -> str | None:
        meta = self._meta(cap)
        produces = meta.get("produces") or []
        if "latitude" in produces or "coordinates" in produces:
            return "location"
        if "address" in produces or "display_name" in produces:
            return "location"
        if "meal_list" in produces:
            return "meal"
        if "book_list" in produces:
            return "book"
        return None

    def _extract_facts(self, cap: str, data: Any) -> list[EvidenceFact]:
        """Flatten an artifact payload into facts.

        Top-level scalar fields are facts directly; nested objects are
        flattened one level with dotted paths. List payloads produce one
        fact per item's first fields (bounded — the evidence packet must
        stay small for the 30B model).

        MODEL-AB-01 renderer fix: a LIST-valued field (e.g. the promoted
        ``book_titles`` array from ``x-artifact-fields``) becomes a single
        list fact so the deterministic renderer can display its items —
        not just "count: N".
        """
        from types import MappingProxyType

        facts: list[EvidenceFact] = []
        if isinstance(data, MappingProxyType):
            data = dict(data)

        def _scalar(v: Any) -> bool:
            return v is not None and not isinstance(v, (dict, list, tuple, MappingProxyType))

        def _add(key: str, value: Any, path: str) -> None:
            facts.append(EvidenceFact(key=key, value=value, source_path=path))

        if isinstance(data, dict):
            for k, v in data.items():
                if _scalar(v):
                    _add(str(k), v, str(k))
                elif isinstance(v, (list, tuple)) and v:
                    # List fact (displayable items — bounded).
                    _add(str(k), list(v)[:6], str(k))
                elif isinstance(v, (dict, MappingProxyType)) and not isinstance(v, list):
                    inner = dict(v) if isinstance(v, MappingProxyType) else v
                    for ik, iv in inner.items():
                        if _scalar(iv):
                            _add(str(ik), iv, f"{k}.{ik}")
        elif isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                for k, v in list(first.items())[:8]:
                    if _scalar(v):
                        _add(str(k), v, f"[0].{k}")
        # Bound: the evidence packet stays compact.
        return facts[:12]


class RequiredEvidenceCompiler:
    """IntentGraph + requested outputs → required facts/entities.

    The reviewer's P0-D.6: required-evidence coverage must be a
    deterministic check — the LLM never decides what was required.
    """

    def __init__(self, user_query: str = "") -> None:
        self._user_query = user_query or ""

    def required_entities(self, structured_intents: dict[str, Any] | None,
                          workflow_nodes: list[dict[str, Any]] | None) -> list[EvidenceEntity]:
        """Entities the response MUST mention: intent-graph entities +
        workflow-node input values traceable to the user query."""
        entities: dict[str, EvidenceEntity] = {}

        def _add(name: str, etype: str) -> None:
            low = name.strip().lower()
            if len(low) < 2:
                return
            if low not in entities:
                entities[low] = EvidenceEntity(
                    entity_id=low, canonical_name=name.strip(), entity_type=etype,
                )

        if isinstance(structured_intents, dict):
            for item in structured_intents.get("intents") or []:
                if not isinstance(item, dict):
                    continue
                for e in item.get("entities") or []:
                    if isinstance(e, str) and e.strip():
                        _add(e, "intent_entity")
                goal = str(item.get("goal") or "")
                # Goal-carried entities ("obtain the coordinates for Lahore").
                for m in re.finditer(
                    r"(?i)(?:for|of|in|at)\s+([a-z][a-z0-9 .'-]{2,30})", goal
                ):
                    cand = m.group(1).strip()
                    low = cand.lower()
                    if low not in {"the coordinates", "those coordinates", "the address"}:
                        _add(cand, "goal_entity")
        # P0-B traceability: a candidate entity is only REAL when the user
        # query names it. The goal extractor can capture sentence tails
        # ("Lahore. if the geocoder returns a result") — the query check
        # rejects everything the user never said.
        q = (self._user_query or "").lower()
        traceable = [e for e in entities.values() if e.entity_id in q]
        if traceable:
            entities = {e.entity_id: e for e in traceable}

        for n in workflow_nodes or []:
            if not isinstance(n, dict):
                continue
            for v in (n.get("inputs") or {}).values():
                if not isinstance(v, str) or not v.strip():
                    continue
                if _PLACEHOLDER_RE.search(v):
                    continue
                low = v.lower()
                if q and low in q and len(low) >= 2:
                    _add(v, "input_entity")
        return list(entities.values())


class GroundingValidator:
    """Deterministic grounding gate: required ⊆ available ⊆ rendered."""

    def check(
        self,
        text: str,
        evidence: list[ResponseEvidence],
        required_entities: list[EvidenceEntity],
    ) -> GroundingCoverage:
        """Validate the rendered text against evidence + requirements.

        Case A (missing execution): required fact absent from AVAILABLE
        evidence — execution/binding, not synthesis.
        Case B (synthesis omission): available but not represented in text.
        Case C (hallucination): text mentions a fact no evidence holds.

        Coverage = represented required evidence / required evidence,
        where a fact counts as represented when one of its VALUES appears
        in the rendered text (value-level, deterministic).
        """
        t = (text or "").lower()
        q_tainted = (self._user_query or "").lower()

        def _value_list(ev: ResponseEvidence) -> list[str]:
            out: list[str] = []
            for f in ev.facts:
                v = f.value
                if isinstance(v, bool) or v is None:
                    continue
                s = str(v).strip()
                if len(s) >= 2 and s.lower() != "none":
                    out.append(s)
            return out

        # Entity representation: each required entity must appear in text
        # (Case B for entities — the "Lahore" omission class).
        missing_entities: list[str] = []
        for ent in required_entities:
            names = [ent.canonical_name, ent.entity_id, *ent.aliases]
            if not any(n and n.lower() in t for n in names):
                missing_entities.append(ent.entity_id)

        # Fact representation: each evidence's facts must contribute at
        # least one NON-query-tainted value to the text (the P2-A credit
        # rule — a response echoing the query earns no credit). An artifact
        # whose only values are query-tainted is still expected to be
        # named via its entity, which the entity check above covers.
        missing_evidence: list[str] = []
        represented = 0
        for ev in evidence:
            values = _value_list(ev)
            if not values:
                continue  # entity-only artifact — covered by entity check
            untainted = [v for v in values if not (q_tainted and v.lower() in q_tainted)]
            if any(v.lower() in t for v in untainted):
                represented += 1
            elif not untainted and ev.entity_id and ev.entity_id in t:
                # ALL values query-tainted: the entity name in text is the
                # only representable evidence (the "Lahore" echo case).
                represented += 1
            else:
                missing_evidence.append(f"{ev.capability_id}:{ev.evidence_id}")

        total_facts = max(1, len(evidence))
        represented_facts = represented
        ratio = round(represented_facts / total_facts, 3)
        if missing_entities:
            ratio = min(ratio, round(1.0 - (len(missing_entities) / max(1, total_facts + len(missing_entities))), 3))

        # Hallucination check: numeric facts in the text that match NO
        # evidence value (Case C — fabricated numbers). Extract numbers
        # from the text and flag any that no evidence holds.
        available_numeric = {
            str(v)
            for ev in evidence for f in ev.facts
            if isinstance(f.value, (int, float)) and not isinstance(f.value, bool)
            for v in [f.value, f"{f.value:g}"]
        }
        hallucinated: list[str] = []
        for num in re.findall(r"\d+\.?\d*", t):
            if num in available_numeric:
                continue
            if num in q_tainted:
                continue  # the user supplied it — echo, not fabrication
            if re.fullmatch(r"1[89]\d\d|20\d\d", num):
                continue  # year-like
            if len(num) == 1 and num in "012":
                continue  # single small ordinals are too noisy
            hallucinated.append(num)
        hallucinated = sorted(set(hallucinated))[:4]

        return GroundingCoverage(
            required_facts=total_facts,
            available_facts=len(evidence),
            represented_facts=represented_facts,
            coverage_ratio=ratio,
            missing_evidence=missing_evidence[:8],
            hallucinated_evidence=hallucinated[:4],
            required_entities_missing=missing_entities,
        )

    def __init__(self, user_query: str = "") -> None:
        self._user_query = user_query or ""
