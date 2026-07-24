"""CapabilityRegistry — dynamic capability discovery from tool metadata.

No hardcoded capabilities. Capabilities are inferred from tool names, tags,
categories, and keywords at registration time. The planner uses capabilities
to map user goals to workflows.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("nexus.agent.registry.capability")


class Capability:
    """A high-level capability that the system can perform.

    Auto-inferred from tool metadata. Capabilities group related tools
    that collectively deliver a user-facing feature.
    """

    def __init__(
        self,
        name: str,
        description: str,
        tool_names: list[str],
        category: str = "general",
    ) -> None:
        self.name = name
        self.description = description
        self.tool_names = sorted(set(tool_names))
        self.category = category

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tool_names": self.tool_names,
            "category": self.category,
        }


# Maximum number of tool names to include in a capability description
_CAPABILITY_TOOL_DESC_LIMIT: int = 5


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
    """
    capabilities: dict[str, dict[str, Any]] = {}

    def _add_tool(cap_name: str, tool: dict[str, Any], desc: str, cat: str) -> None:
        if cap_name not in capabilities:
            capabilities[cap_name] = {
                "name": cap_name,
                "description": desc,
                "tool_names": [],
                "category": cat,
            }
        capabilities[cap_name]["tool_names"].append(tool["name"])

    for tool in tools:
        name: str = tool.get("name", "")
        tags: list[str] = tool.get("tags", []) or []
        category: str = tool.get("category", "") or ""
        purpose: str = tool.get("purpose", "") or tool.get("description", "") or ""

        # 1. Category-based grouping (most explicit)
        if category and category != "general":
            _add_tool(category, tool, f"Tools in category: {category}", category)
            continue

        # 2. Tag-based grouping (second most explicit)
        tag_based = False
        for tag in sorted(tags):
            if tag and tag not in ("read", "write", "admin", "create", "update", "delete", "utility"):
                _add_tool(tag, tool, f"Tools tagged: {tag}", tag)
                tag_based = True
                break

        if tag_based:
            continue

        # 3. Prefix-based grouping (inferred from naming convention)
        prefix = name.split("_")[0] if "_" in name else ""
        if prefix:
            cap_key = f"{prefix}_operations"
            desc = f"Operations with '{prefix}' prefix"
            _add_tool(cap_key, tool, desc, cap_key)
            continue

        # 4. Singleton capability (no grouping signal found)
        cap_key = f"tool_{name}"
        _add_tool(cap_key, tool, f"Capability for: {name}", "singleton")

    # Deduplicate tool names within each capability
    result: dict[str, Capability] = {}
    for cap_name, data in capabilities.items():
        data["tool_names"] = sorted(set(data["tool_names"]))
        # Build description from tool purposes if they share a common theme
        result[cap_name] = Capability(**data)

    return result


class CapabilityRegistry:
    """Auto-populated registry of system capabilities.

    Capabilities are inferred from tool metadata at registration time.
    No hardcoded capability names.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._tool_names: set[str] = set()

    def register_from_tools(self, tools: list[dict[str, Any]]) -> None:
        """Register capabilities inferred from tool metadata.

        Fully dynamic — no hardcoded capabilities.
        """
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
        """Find all capabilities that include the given tool."""
        return [c for c in self._capabilities.values() if tool_name in c.tool_names]

    def find_by_description(self, query: str) -> list[tuple[Capability, float]]:
        """Find capabilities whose description matches the query keywords.

        Simple keyword scoring — no LLM, no embeddings.
        """
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


_singleton_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    """Get the singleton CapabilityRegistry instance."""
    global _singleton_registry
    if _singleton_registry is None:
        _singleton_registry = CapabilityRegistry()
    return _singleton_registry


def populate_from_tools(tools: list[dict[str, Any]]) -> None:
    """Convenience: register capabilities from tool list."""
    registry = get_capability_registry()
    registry.register_from_tools(tools)
