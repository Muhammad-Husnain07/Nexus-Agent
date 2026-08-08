"""GlobalContext — Immutable per-deployment static knowledge.

Holds references to the CompiledCapabilityGraph, Ontology hierarchy,
static schemas, and O(1) capability→providers hash map.  Instantiated once
at server startup and injected into the runtime.  Never serialized into
the graph state.

The O(1) ``capability_providers`` dict is the sole runtime lookup for
provider/endpoint selection — no linear scanning or DB queries at 500+
tool scale.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GlobalContext(BaseModel):
    """Immutable per-deployment context — never serialized into graph state.

    Attributes:
        compiled_graph: The compiled capability graph artifact.
        ontology: Ontology hierarchy for semantic resolution.
        static_schemas: Static schema definitions keyed by name.
        registry_checksum: Checksum of the registry at load time.
        capability_providers: O(1) capability_id → candidate_providers hash map.
            Keys are capability names (e.g. ``"get_weather"``). Values are lists
            of provider dicts with endpoint metadata for strategy selection.
        capability_keywords: O(1) keyword→capability mapping for router classification.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    compiled_graph: Any = Field(default=None, description="CompiledCapabilityGraph instance")
    ontology: Any = Field(default=None, description="Ontology hierarchy")
    static_schemas: dict[str, Any] = Field(
        default_factory=dict,
        description="Static schema definitions",
    )
    registry_checksum: str = Field(
        default="",
        description="Registry version checksum at load time",
    )
    capability_providers: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict,
        description="O(1) capability_id → candidate_providers hash map",
    )
    capability_keywords: dict[str, list[str]] = Field(
        default_factory=dict,
        description="O(1) keyword → capability name list for router classification",
    )
    alias_index: dict[str, str] = Field(
        default_factory=dict,
        description="O(1) explicit alias → canonical capability name (operator-declared only)",
    )
    domain_index: dict[str, list[str]] = Field(
        default_factory=dict,
        description="O(1) domain/category → capability name list (domain-first narrowing)",
    )
    capability_index: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="capability name → metadata {id, domain, aliases, logical_op_name}",
    )

    def get_capability_providers(self, capability_id: str) -> list[dict[str, Any]]:
        """O(1) lookup of candidate providers for a capability."""
        return self.capability_providers.get(capability_id, [])

    def resolve_alias(self, alias: str) -> str | None:
        """O(1) explicit alias → capability lookup (exact only)."""
        return self.alias_index.get(alias) or self.alias_index.get(alias.strip().lower())

    def capabilities_in_domain(self, domain: str) -> list[str]:
        """O(1) domain → capability list (exact domain match)."""
        return self.domain_index.get(domain, [])

    def capability_meta(self, name: str) -> dict[str, Any] | None:
        """O(1) capability metadata lookup (id, domain, aliases)."""
        return self.capability_index.get(name)

    def match_capabilities(self, keywords: list[str]) -> list[str]:
        """O(1) keyword-based capability matching for the Router.

        Returns capability names that match any of the given keywords.
        Replaces the old ``_match_tools()`` that scanned ``available_tools`` in state.
        """
        matched: set[str] = set()
        for kw in keywords:
            for cap_name in self.capability_keywords.get(kw.lower(), []):
                matched.add(cap_name)
        return list(matched)

    @classmethod
    async def build(
        cls,
        graph: Any,
        *,
        tool_session: Any = None,
    ) -> GlobalContext:
        """Build a GlobalContext from a CompiledCapabilityGraph + Tool metadata.

        The compiled graph supplies providers/keywords; the Tool table
        (queried lazily with ``tool_session`` when provided) supplies the
        explicit alias + domain indexes. Both are metadata-driven.
        """
        ctx = cls.from_compiled_graph(graph)
        try:
            if tool_session is not None:
                ctx = await ctx.with_tool_metadata(tool_session)
        except Exception as exc:
            logger = __import__("structlog").get_logger("nexus.context.global_context")
            logger.warning("global_context.tool_metadata_failed", error=str(exc)[:200])
        return ctx

    async def with_tool_metadata(self, session: Any) -> GlobalContext:
        """Return a new GlobalContext enriched with Tool alias/domain metadata.

        Also prebuilds a normalized search document per capability (name +
        aliases + capabilities + category + tags + keywords + produces +
        consumes + related + description + purpose + example prompts) so the
        retriever's BM25 corpus is assembled once at build time, not per
        request.
        """
        from sqlalchemy import select

        from nexus.db.models.registry import (
            CapabilityModel,
            EndpointModel,
            ProviderModel,
        )
        from nexus.db.models.tool import Tool

        alias_index = dict(self.alias_index)
        domain_index = dict(self.domain_index)
        capability_index = dict(self.capability_index)
        capability_providers = dict(self.capability_providers)
        # Registered tools' keywords must join the O(1) keyword→capability
        # pool too — otherwise retrieval's candidate pool (built from
        # ``capability_keywords``) never contains tools registered after the
        # compiled graph was built and BM25 cannot rank them.
        keywords = dict(self.capability_keywords)

        # Registered tools' provider/endpoint rows join the provider universe
        # (the compiled graph's providers are not enough): the resolver,
        # executor auth fallback, and the availability fact (a capability is
        # executable only when a provider with a URL exists) all read
        # ``capability_providers``.
        try:
            prov_rows = await session.execute(
                select(CapabilityModel.name, ProviderModel.name, EndpointModel)
                .join(ProviderModel, ProviderModel.capability_id == CapabilityModel.id)
                .join(EndpointModel, EndpointModel.provider_id == ProviderModel.id)
                .where(ProviderModel.enabled.is_(True), EndpointModel.enabled.is_(True))
            )
            for cap_name, prov_name, endp in prov_rows.all():
                if not endp.url:
                    continue
                capability_providers.setdefault(cap_name, []).append({
                    "provider_name": prov_name,
                    "url": endp.url,
                    "http_method": endp.http_method or "GET",
                    "auth_type": endp.auth_type or "none",
                    "auth_ref": "",
                })
        except Exception:
            pass

        result = await session.execute(
            select(
                Tool.name, Tool.aliases, Tool.category, Tool.id,
                Tool.capabilities, Tool.produces, Tool.consumes, Tool.related,
                Tool.tags, Tool.keywords, Tool.description, Tool.purpose,
                Tool.examples, Tool.cacheable, Tool.enabled,
                Tool.input_schema, Tool.requires_approval, Tool.risk_level,
                Tool.idempotent, Tool.compensating_operation,
            )
        )
        for (
            t_name, t_aliases, t_category, t_id,
            t_capabilities, t_produces, t_consumes, t_related,
            t_tags, t_keywords, t_description, t_purpose,
            t_examples, t_cacheable, t_enabled,
            t_input_schema, t_requires_approval, t_risk_level,
            t_idempotent, t_compensating_operation,
        ) in result.all():
            # Availability fact: disabled tools are NEVER indexed — plans must
            # never include unavailable capabilities (runtime contract §7).
            if t_enabled is False:
                continue
            # Domain index: from the tool's own category metadata.
            if t_category:
                domain_index.setdefault(t_category, [])
                if t_name not in domain_index[t_category]:
                    domain_index[t_category].append(t_name)
            # Keyword pool: every tool keyword maps to this capability.
            for kw in (t_keywords or []):
                if isinstance(kw, str) and kw.strip():
                    kw_lower = kw.strip().lower()
                    keywords.setdefault(kw_lower, [])
                    if t_name not in keywords[kw_lower]:
                        keywords[kw_lower].append(t_name)
            # Alias index: EXPLICIT operator-declared aliases only.
            for alias in (t_aliases or []):
                if isinstance(alias, str) and alias.strip():
                    alias_index[alias.strip().lower()] = t_name
            # Capability metadata.
            meta = capability_index.get(t_name, {})
            meta["id"] = str(t_id)
            meta["domain"] = t_category or ""
            meta["aliases"] = list(t_aliases or [])
            meta["capabilities"] = list(t_capabilities or [])
            meta["produces"] = list(t_produces or [])
            meta["consumes"] = list(t_consumes or [])
            meta["related"] = list(t_related or [])
            meta["cacheable"] = bool(t_cacheable)
            meta["description"] = str(t_description or "")
            meta["purpose"] = str(t_purpose or "")
            meta["keywords"] = list(t_keywords or [])
            meta["requires_approval"] = bool(t_requires_approval)
            meta["risk_level"] = str(t_risk_level or "low")
            # Required-property list from the input schema — feeds the
            # PlanValidatorNode's missing-input check (metadata-driven).
            if isinstance(t_input_schema, dict):
                meta["input_schema"] = t_input_schema
                req = t_input_schema.get("required")
                if isinstance(req, list):
                    meta["input_required"] = [str(r) for r in req if isinstance(r, str)]
                # x-aliases per property (for alias-aware validation/coercion).
                aliases: dict[str, list[str]] = {}
                props = t_input_schema.get("properties")
                if isinstance(props, dict):
                    for pname, pdef in props.items():
                        if isinstance(pdef, dict):
                            p_aliases = pdef.get("x-aliases")
                            if isinstance(p_aliases, list):
                                aliases[str(pname)] = [str(a) for a in p_aliases if isinstance(a, str)]
                if aliases:
                    meta["input_aliases"] = aliases
            meta["examples"] = [str(e.get("user_prompt")) for e in (t_examples or []) if isinstance(e, dict) and e.get("user_prompt")]
            meta["logical_op_name"] = t_name
            # Prebuilt normalized search document (retriever corpus source).
            example_prompts: list[str] = []
            for ex in (t_examples or []):
                if isinstance(ex, dict) and ex.get("user_prompt"):
                    example_prompts.append(str(ex["user_prompt"]))
            doc_parts = [
                t_name,
                *[str(a) for a in (t_aliases or [])],
                *[str(c) for c in (t_capabilities or [])],
                str(t_category or ""),
                *[str(tag) for tag in (t_tags or [])],
                *[str(k) for k in (t_keywords or [])],
                *[str(p) for p in (t_produces or [])],
                *[str(c) for c in (t_consumes or [])],
                *[str(r) for r in (t_related or [])],
                str(t_description or ""),
                str(t_purpose or ""),
                *example_prompts,
            ]
            meta["search_doc"] = " ".join(p for p in doc_parts if p)
            # Capability contract (execution policy etc.) — the same shape the
            # registry syncs to CapabilityModel.contract, so policy readers
            # work identically from GC metadata.
            try:
                from types import SimpleNamespace as _NS
                from nexus.tools.registry import _build_tool_contract

                meta["contract"] = _build_tool_contract(_NS(
                    idempotent=bool(t_idempotent),
                    risk_level=str(t_risk_level or "low"),
                    requires_approval=bool(t_requires_approval),
                    cacheable=bool(t_cacheable),
                    capabilities=list(t_capabilities or []),
                    related=list(t_related or []),
                    validation_rules=None,
                    compensating_operation=t_compensating_operation,
                ))
            except Exception:
                pass
            capability_index[t_name] = meta

        return GlobalContext(
            compiled_graph=self.compiled_graph,
            ontology=self.ontology,
            static_schemas=self.static_schemas,
            registry_checksum=self.registry_checksum,
            capability_providers=capability_providers,
            capability_keywords=keywords,
            alias_index=alias_index,
            domain_index=domain_index,
            capability_index=capability_index,
        )

    @classmethod
    def from_compiled_graph(cls, graph: Any) -> GlobalContext:
        """Build a GlobalContext from a CompiledCapabilityGraph, pre-computing O(1) maps."""
        providers: dict[str, list[dict[str, Any]]] = {}
        keywords: dict[str, list[str]] = {}
        capability_index: dict[str, dict[str, Any]] = {}

        if hasattr(graph, "capability_providers"):
            providers = dict(graph.capability_providers)

        if hasattr(graph, "nodes"):
            for cap_name, node in graph.nodes.items():
                # Derive keywords from capability name, tags, and produces fields
                cap_keywords = set()
                parts = cap_name.replace("_", " ").lower().split()
                for p in parts:
                    if len(p) > 2:
                        cap_keywords.add(p)
                if hasattr(node, "produces"):
                    for prod in (node.produces or []):
                        for p in prod.replace("_", " ").lower().split():
                            if len(p) > 2:
                                cap_keywords.add(p)
                if hasattr(node, "consumes"):
                    for con in (node.consumes or []):
                        for p in con.replace("_", " ").lower().split():
                            if len(p) > 2:
                                cap_keywords.add(p)
                # Add keywords from description and purpose
                for text in [getattr(node, "description", ""), getattr(node, "purpose", "")]:
                    if text:
                        for word in re.findall(r"\b[a-z]{3,}\b", text.lower()):
                            cap_keywords.add(word)
                for kw in cap_keywords:
                    keywords.setdefault(kw, []).append(cap_name)

                # Seed capability metadata for EVERY graph node — the
                # tool-table enrichment (with_tool_metadata) merges on top.
                logical_op = getattr(node, "logical_op_name", "") or cap_name
                meta = capability_index.get(cap_name, {})
                meta.setdefault("id", "")
                meta["domain"] = meta.get("domain") or (cap_name.split("_", 1)[0] if "_" in cap_name else "")
                meta.setdefault("aliases", [])
                meta.setdefault("capabilities", [])
                meta["keywords"] = list(cap_keywords)
                meta.setdefault("produces", list(getattr(node, "produces", []) or []))
                meta.setdefault("consumes", list(getattr(node, "consumes", []) or []))
                meta.setdefault("related", [])
                meta.setdefault("cacheable", True)
                meta.setdefault("description", str(getattr(node, "description", "") or ""))
                meta.setdefault("purpose", str(getattr(node, "purpose", "") or ""))
                meta["logical_op_name"] = logical_op
                capability_index[cap_name] = meta
                # Also index under the logical op name (dual-key, matching
                # capability_providers so the executor never misses).
                if logical_op and logical_op != cap_name:
                    capability_index.setdefault(logical_op, dict(meta))

        checksum = getattr(graph, "registry_checksum", "") or ""

        return cls(
            compiled_graph=graph,
            registry_checksum=checksum,
            capability_providers=providers,
            capability_keywords=keywords,
            capability_index=capability_index,
        )


_GLOBAL: GlobalContext | None = None


def get_global_context() -> GlobalContext:
    """Return the singleton GlobalContext, or a default if not initialized."""
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = GlobalContext()
    return _GLOBAL


def set_global_context(ctx: GlobalContext) -> None:
    """Set the singleton GlobalContext (called once at server startup)."""
    global _GLOBAL
    _GLOBAL = ctx


def reset_global_context() -> None:
    """Reset the singleton (used in testing)."""
    global _GLOBAL
    _GLOBAL = None
