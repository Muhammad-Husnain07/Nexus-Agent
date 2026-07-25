"""CapabilityRegistry — dynamic capability discovery from tool metadata.

No hardcoded capabilities. Capabilities are inferred from tool names, tags,
categories, and keywords at registration time. The planner uses capabilities
to map user goals to workflows.

Each capability now declares:
- ``consumes``: Artifact names it requires as input
- ``produces``: Artifact names it produces as output  
- ``preconditions``: Conditions that must be true before execution
- ``postconditions``: Conditions that are true after execution
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("nexus.agent.registry.capability")


class Capability:
    """A high-level capability that the system can perform.

    Auto-inferred from tool metadata. Capabilities group related tools
    that collectively deliver a user-facing feature.

    Attributes:
        name: Unique capability name.
        description: Human-readable description.
        tool_names: Tools that can fulfill this capability.
        category: Functional category.
        consumes: Artifact names required as input.
        produces: Artifact names produced as output.
        preconditions: Predicates that must be true before execution.
        postconditions: Predicates that are true after execution.
        cost_estimate: Estimated monetary cost (0.0-1.0 scale).
        latency_estimate: Expected latency (LOW, MEDIUM, HIGH).
    """

    def __init__(
        self,
        name: str,
        description: str,
        tool_names: list[str],
        category: str = "general",
        consumes: list[str] | None = None,
        produces: list[str] | None = None,
        preconditions: list[str] | None = None,
        postconditions: list[str] | None = None,
        cost_estimate: float = 0.001,
        latency_estimate: str = "LOW",
    ) -> None:
        self.name = name
        self.description = description
        self.tool_names = sorted(set(tool_names))
        self.category = category
        self.consumes = consumes or []
        self.produces = produces or []
        self.preconditions = preconditions or []
        self.postconditions = postconditions or []
        self.cost_estimate = cost_estimate
        self.latency_estimate = latency_estimate

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tool_names": self.tool_names,
            "category": self.category,
            "consumes": self.consumes,
            "produces": self.produces,
            "preconditions": self.preconditions,
            "postconditions": self.postconditions,
            "cost_estimate": self.cost_estimate,
            "latency_estimate": self.latency_estimate,
        }


# Maximum number of tool names to include in a capability description
_CAPABILITY_TOOL_DESC_LIMIT: int = 5


def _infer_artifact_names_from_schema(schema: dict[str, Any]) -> list[str]:
    """Extract artifact field names from a JSON Schema."""
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties", {})
    if not isinstance(props, dict):
        return []
    return list(props.keys())


def _infer_capabilities_from_tools(
    tools: list[dict[str, Any]],
) -> dict[str, Capability]:
    """Infer capabilities from tool metadata without hardcoded names.

    Strategy:
    1. Group tools by their ``category`` field (most explicit signal).
    2. Group tools by shared ``tags``.
    3. For uncategorized tools, derive capability name from common name prefixes
       (e.g., ``get_*`` -> ``data_retrieval``, ``search_*`` -> ``search``).
    4. Tools not matching any group get a default singleton capability.

    Each capability's ``consumes`` and ``produces`` are inferred from the
    input/output schemas of its constituent tools.
    """
    capabilities: dict[str, dict[str, Any]] = {}

    def _add_tool(cap_name: str, tool: dict[str, Any], desc: str, cat: str) -> None:
        if cap_name not in capabilities:
            capabilities[cap_name] = {
                "name": cap_name,
                "description": desc,
                "tool_names": [],
                "category": cat,
                "consumes": [],
                "produces": [],
                "preconditions": [],
                "postconditions": [],
                "cost_estimate": 0.001,
                "latency_estimate": "LOW",
            }

        entry = capabilities[cap_name]
        entry["tool_names"].append(tool["name"])

        # Infer consumes from input schema
        input_schema = tool.get("input_schema", {}) or {}
        for field in _infer_artifact_names_from_schema(input_schema):
            if field not in entry["consumes"]:
                entry["consumes"].append(field)

        # Infer produces from output schema
        output_schema = tool.get("output_schema", {}) or {}
        for field in _infer_artifact_names_from_schema(output_schema):
            if field not in entry["produces"]:
                entry["produces"].append(field)

        # Set preconditions: required input fields become preconditions
        required = input_schema.get("required", []) if isinstance(input_schema, dict) else []
        for req in required:
            pred = f"has.{req}"
            if pred not in entry["preconditions"]:
                entry["preconditions"].append(pred)

        # Set postconditions: success means output produced
        for field in _infer_artifact_names_from_schema(output_schema):
            post = f"{field}.generated"
            if post not in entry["postconditions"]:
                entry["postconditions"].append(post)

    for tool in tools:
        name: str = tool.get("name", "")
        tags: list[str] = tool.get("tags", []) or []
        category: str = tool.get("category", "") or ""

        if category and category != "general":
            _add_tool(category, tool, f"Capability: {category}", category)
            continue

        tag_based = False
        for tag in sorted(tags):
            if tag and tag not in ("read", "write", "admin", "create", "update", "delete", "utility"):
                _add_tool(tag, tool, f"Capability tagged: {tag}", tag)
                tag_based = True
                break

        if tag_based:
            continue

        prefix = name.split("_")[0] if "_" in name else ""
        if prefix:
            cap_key = f"{prefix}_operations"
            _add_tool(cap_key, tool, f"Operations with '{prefix}' prefix", cap_key)
            continue

        cap_key = f"tool_{name}"
        _add_tool(cap_key, tool, f"Capability for: {name}", "singleton")

    result: dict[str, Capability] = {}
    for cap_name, data in capabilities.items():
        data["tool_names"] = sorted(set(data["tool_names"]))
        data["consumes"] = sorted(set(data["consumes"]))
        data["produces"] = sorted(set(data["produces"]))
        data["preconditions"] = sorted(set(data["preconditions"]))
        data["postconditions"] = sorted(set(data["postconditions"]))
        result[cap_name] = Capability(**data)

    return result


class CapabilityRegistry:
    """Auto-populated registry of system capabilities with artifact contracts.

    Capabilities are inferred from tool metadata at registration time.
    Each capability declares what artifacts it consumes and produces.
    No hardcoded capability names.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._tool_names: set[str] = set()

    def register_from_tools(self, tools: list[dict[str, Any]]) -> None:
        """Register capabilities inferred from tool metadata."""
        current_tool_names = {t.get("name", "") for t in tools if t.get("name")}
        if current_tool_names == self._tool_names:
            return

        self._tool_names = current_tool_names
        self._capabilities = _infer_capabilities_from_tools(tools)
        logger.info(
            "capability_registry.registered",
            count=len(self._capabilities),
            capability_names=list(self._capabilities.keys()),
        )

    def get_capability(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def get_capabilities(self) -> list[Capability]:
        return list(self._capabilities.values())

    def find_capabilities(self, tool_name: str) -> list[Capability]:
        return [c for c in self._capabilities.values() if tool_name in c.tool_names]

    def find_by_description(self, query: str) -> list[tuple[Capability, float]]:
        tokens = query.lower().split()
        scored: list[tuple[Capability, float]] = []
        for cap in self._capabilities.values():
            score = 0.0
            text = f"{cap.name} {cap.description} {' '.join(cap.tool_names)}".lower()
            for token in tokens:
                if token in text:
                    score += 1.0
            if score > 0:
                scored.append((cap, score / max(len(tokens), 1)))
        return sorted(scored, key=lambda x: -x[1])

    def find_chain(
        self,
        from_artifacts: set[str],
        to_artifact: str,
    ) -> list[list[Capability]]:
        """Find all capability chains that produce ``to_artifact`` given ``from_artifacts``.

        Uses BFS over the capability graph (consumes → produces edges).
        Returns all valid paths (list of capabilities) that transform
        available artifacts into the target artifact.

        This is the foundation for the A*-based Requirement Resolver.
        """
        # Build adjacency: capability → list of capabilities it can feed
        adj: dict[str, list[str]] = {}
        for cap in self._capabilities.values():
            adj.setdefault(cap.name, [])
            for other in self._capabilities.values():
                if cap is other:
                    continue
                # If this capability produces something the other consumes
                if set(cap.produces) & set(other.consumes):
                    adj[cap.name].append(other.name)

        # BFS from capabilities that can use from_artifacts
        start_caps = [
            c for c in self._capabilities.values()
            if set(c.consumes) & from_artifacts or not c.consumes
        ]

        paths: list[list[Capability]] = []
        visited: set[str] = set()

        def bfs(current: list[Capability]) -> None:
            last = current[-1]
            if to_artifact in last.produces:
                paths.append(list(current))
                return
            if last.name in visited:
                return
            visited.add(last.name)
            for next_name in adj.get(last.name, []):
                next_cap = self._capabilities.get(next_name)
                if next_cap and next_cap.name not in {c.name for c in current}:
                    current.append(next_cap)
                    bfs(current)
                    current.pop()
            visited.discard(last.name)

        for cap in start_caps:
            bfs([cap])

        return paths


_singleton_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    global _singleton_registry
    if _singleton_registry is None:
        _singleton_registry = CapabilityRegistry()
    return _singleton_registry


def populate_from_tools(tools: list[dict[str, Any]]) -> None:
    registry = get_capability_registry()
    registry.register_from_tools(tools)
