"""Offline Registry Compiler — compiles DB metadata into a runtime-ready capability graph.

CLI command: ``nexus compile-registry``

Reads CapabilityModel, ProviderModel, EndpointModel, GoalTemplateModel from the DB.
Validates contracts, checks for missing producers, detects cycles.
Generates a CompiledCapabilityGraph that the runtime reads — never computes ontology.

No hardcoded capability names. All data comes from DB metadata.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger("nexus.compiler.registry_compiler")


# ============================================================================
# Compiled Graph Data Structures (serializable, runtime-ready)
# ============================================================================


class CompiledCapabilityNode:
    """A single node in the compiled capability graph.

    Serialized to JSON for runtime consumption. No ORM references.
    """

    def __init__(
        self,
        name: str,
        consumes: list[str] | None = None,
        produces: list[str] | None = None,
        preconditions: list[str] | None = None,
        postconditions: list[str] | None = None,
        providers: list[dict[str, Any]] | None = None,
        version: int = 1,
    ) -> None:
        self.name = name
        self.consumes = consumes or []
        self.produces = produces or []
        self.preconditions = preconditions or []
        self.postconditions = postconditions or []
        self.providers = providers or []
        self.version = version

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "consumes": self.consumes,
            "produces": self.produces,
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "providers": self.providers,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> CompiledCapabilityNode:
        return CompiledCapabilityNode(
            name=data["name"],
            consumes=data.get("consumes", []),
            produces=data.get("produces", []),
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            providers=data.get("providers", []),
            version=data.get("version", 1),
        )


class CompiledGoalTemplate:
    """A compiled goal template — maps trigger actions to capability sequences.

    No expansion logic at runtime — the compiler pre-resolves the capability
    sequence and stores it as a dependency chain.
    """

    def __init__(
        self,
        name: str,
        trigger_action: str,
        capability_chain: list[str],
        version: int = 1,
    ) -> None:
        self.name = name
        self.trigger_action = trigger_action
        self.capability_chain = capability_chain
        self.version = version

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trigger_action": self.trigger_action,
            "capability_chain": self.capability_chain,
            "version": self.version,
        }


class CompiledCapabilityGraph:
    """The complete compiled capability graph — loaded at runtime.

    Contains all capabilities, their providers/endpoints, goal templates,
    and pre-computed adjacency lists for dependency resolution.

    Runtime reads this graph. Never queries ontology or computes schema matches.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, CompiledCapabilityNode] = {}
        self.goal_templates: dict[str, CompiledGoalTemplate] = {}
        self.adjacency: dict[str, list[str]] = {}  # capability → capabilities it can feed
        self.ontology_parents: dict[str, str] = {}  # capability → parent
        self.missing_producers: list[str] = []
        self.cycles: list[list[str]] = []
        self.compiled_at: str = ""
        self.source_registry_version: int = 0

    def add_node(self, node: CompiledCapabilityNode) -> None:
        self.nodes[node.name] = node

    def add_template(self, template: CompiledGoalTemplate) -> None:
        self.goal_templates[template.trigger_action] = template

    def build_adjacency(self) -> None:
        """Build producer→consumer adjacency from consumes/produces fields."""
        self.adjacency = {}
        for name_a, node_a in self.nodes.items():
            for name_b, node_b in self.nodes.items():
                if name_a == name_b:
                    continue
                if set(node_a.produces) & set(node_b.consumes):
                    self.adjacency.setdefault(name_a, []).append(name_b)

    def find_missing_producers(self) -> list[str]:
        """Find capabilities whose consumed artifacts have no producer."""
        all_produced: set[str] = set()
        for node in self.nodes.values():
            all_produced.update(node.produces)
        required: set[str] = set()
        for node in self.nodes.values():
            required.update(node.consumes)
        self.missing_producers = sorted(required - all_produced)
        return self.missing_producers

    def detect_cycles(self) -> list[list[str]]:
        """DFS cycle detection on the capability graph."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in self.nodes}
        cycles: list[list[str]] = []
        path: list[str] = []

        def dfs(node: str) -> None:
            color[node] = GRAY
            path.append(node)
            for neighbor in self.adjacency.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    cycle = path[path.index(neighbor):] + [neighbor]
                    cycles.append(cycle)
                if color[neighbor] == WHITE:
                    dfs(neighbor)
            path.pop()
            color[node] = BLACK

        for node in self.nodes:
            if color[node] == WHITE:
                dfs(node)

        self.cycles = cycles
        return cycles

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "goal_templates": {k: v.to_dict() for k, v in self.goal_templates.items()},
            "adjacency": self.adjacency,
            "ontology_parents": self.ontology_parents,
            "missing_producers": self.missing_producers,
            "cycles": self.cycles,
            "compiled_at": self.compiled_at,
            "source_registry_version": self.source_registry_version,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> CompiledCapabilityGraph:
        graph = CompiledCapabilityGraph()
        for name, node_data in data.get("nodes", {}).items():
            graph.nodes[name] = CompiledCapabilityNode.from_dict(node_data)
        for action, tmpl_data in data.get("goal_templates", {}).items():
            graph.goal_templates[action] = CompiledGoalTemplate(**tmpl_data)
        graph.adjacency = data.get("adjacency", {})
        graph.ontology_parents = data.get("ontology_parents", {})
        graph.missing_producers = data.get("missing_producers", [])
        graph.cycles = data.get("cycles", [])
        graph.compiled_at = data.get("compiled_at", "")
        graph.source_registry_version = data.get("source_registry_version", 0)
        return graph


# ============================================================================
# Compiler
# ============================================================================


async def compile_registry(
    session_factory: Any = None,
    output_path: str | None = None,
) -> CompiledCapabilityGraph:
    """Read DB metadata and compile into a runtime-ready capability graph.

    Args:
        session_factory: Optional async DB session factory. If None, uses default.
        output_path: Optional JSON file path to write the compiled graph.

    Returns:
        A ``CompiledCapabilityGraph`` ready for runtime consumption.
    """
    import time

    graph = CompiledCapabilityGraph()
    graph.compiled_at = datetime.now(timezone.utc).isoformat()

    try:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from nexus.db.models.registry import (
            CapabilityModel,
            EndpointModel,
            GoalTemplateModel,
            ProviderModel,
        )

        if session_factory is None:
            from nexus.db.base import async_session as session_factory

        async with session_factory() as session:
            # ── Load capabilities with eager-loaded relationships ──
            from sqlalchemy.orm import selectinload

            result = await session.execute(
                select(CapabilityModel)
                .where(CapabilityModel.enabled == True)  # noqa: E712
                .options(
                    selectinload(CapabilityModel.providers).selectinload(ProviderModel.endpoints)
                )
            )
            capabilities = result.scalars().all()

            for cap in capabilities:
                providers_list = []
                for prov in cap.providers or []:
                    if not prov.enabled:
                        continue
                    endpoints_list = []
                    for ep in prov.endpoints or []:
                        if not ep.enabled:
                            continue
                        endpoints_list.append({
                            "url": ep.url,
                            "http_method": ep.http_method,
                            "auth_type": ep.auth_type,
                            "region": ep.region,
                            "weight": ep.weight,
                        })
                    providers_list.append({
                        "name": prov.name,
                        "cost_per_call": prov.cost_per_call,
                        "sla_p99_ms": prov.sla_p99_ms,
                        "privacy_level": prov.privacy_level,
                        "reliability_score": prov.reliability_score,
                        "rate_limit_per_minute": prov.rate_limit_per_minute,
                        "retry_policy": prov.retry_policy,
                        "circuit_breaker_threshold": prov.circuit_breaker_threshold,
                        "endpoints": endpoints_list,
                    })

                node = CompiledCapabilityNode(
                    name=cap.name,
                    consumes=list(cap.consumes or []),
                    produces=list(cap.produces or []),
                    preconditions=list(cap.preconditions or []),
                    postconditions=list(cap.postconditions or []),
                    providers=providers_list,
                    version=cap.version or 1,
                )
                graph.add_node(node)

                if cap.ontology_parent:
                    graph.ontology_parents[cap.name] = cap.ontology_parent

            # ── Build adjacency ──────────────────────────────────────
            graph.build_adjacency()

            # ── Load goal templates ──────────────────────────────────
            result = await session.execute(
                select(GoalTemplateModel).where(GoalTemplateModel.enabled == True)  # noqa: E712
            )
            templates = result.scalars().all()
            for tmpl in templates:
                cap_chain = [c.name for c in (tmpl.capabilities or []) if c.enabled]
                ct = CompiledGoalTemplate(
                    name=tmpl.name,
                    trigger_action=tmpl.trigger_action,
                    capability_chain=cap_chain,
                    version=tmpl.version or 1,
                )
                graph.add_template(ct)

            # ── Validate ─────────────────────────────────────────────
            graph.find_missing_producers()
            graph.detect_cycles()

    except Exception as exc:
        logger.error("compiler.registry_failed", error=str(exc))
        raise

    # ── Report ──────────────────────────────────────────────────────
    logger.info(
        "compiler.registry_compiled",
        nodes=len(graph.nodes),
        templates=len(graph.goal_templates),
        edges=sum(len(v) for v in graph.adjacency.values()),
        missing_producers=len(graph.missing_producers),
        cycles=len(graph.cycles),
    )

    # ── Write output ────────────────────────────────────────────────
    if output_path:
        with open(output_path, "w") as f:
            f.write(graph.to_json())
        logger.info("compiler.registry_written", path=output_path)

    return graph


# ============================================================================
# CLI Entry Point
# ============================================================================


async def main():
    """CLI entry point: ``nexus compile-registry``."""
    import argparse

    parser = argparse.ArgumentParser(description="Nexus Registry Compiler")
    parser.add_argument("--output", "-o", default=None, help="Output JSON file path")
    parser.add_argument("--check", action="store_true", help="Check for errors without writing")
    args = parser.parse_args()

    graph = await compile_registry(output_path=args.output)

    if graph.missing_producers:
        logger.warning("compiler.missing_producers", fields=graph.missing_producers)

    if graph.cycles:
        logger.error("compiler.cycles_detected", cycles=graph.cycles)
        sys.exit(1)

    if args.check:
        if graph.missing_producers or graph.cycles:
            sys.exit(1)
        logger.info("compiler.check_passed")

    logger.info("compiler.complete")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
