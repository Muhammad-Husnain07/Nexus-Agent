"""Goal Registry — maps user-facing goals to required capabilities.

Goals are the top of the 5-tier hierarchy:
  Intent → Goal → Capability → Artifact → Tool

A goal represents what the user wants to accomplish (e.g., "Get Weather",
"Compare Prices"). Each goal maps to a set of capabilities that must be
executed, each capability consumes and produces typed Artifacts.

No hardcoded goal names. Goals are inferred from tool metadata —
specifically from tool categories, name prefixes, and purposes.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger("nexus.agent.registry.goal")


class Goal:
    """A user-facing goal that maps to capabilities.

    Attributes:
        name: Goal name (e.g., "weather_retrieval", "bookmark_management").
        capabilities: Names of capabilities required to fulfill this goal.
        description: Human-readable description.
    """

    def __init__(
        self,
        name: str,
        capabilities: list[str],
        description: str = "",
    ) -> None:
        self.name = name
        self.capabilities = sorted(set(capabilities))
        self.description = description

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capabilities": list(self.capabilities),
            "description": self.description,
        }


def _goal_name_from_tool(tool: dict[str, Any]) -> str:
    """Derive a goal name from a tool's metadata.

    Strategy:
    1. Use the tool's ``category`` field if set.
    2. Use the tool's name prefix (e.g., ``get_`` → ``data_retrieval``).
    3. Use the tool's tag list, picking the most specific tag.
    4. Fall back to the tool name itself.
    """
    category = tool.get("category", "") or ""
    if category and category != "general":
        return category

    name = tool.get("name", "")
    if "_" in name:
        prefix = name.split("_")[0]
        # Map verb prefixes to goal areas
        verb_map = {
            "get": "data_retrieval",
            "find": "search",
            "search": "search",
            "predict": "prediction",
            "create": "creation",
            "update": "modification",
            "patch": "modification",
            "delete": "deletion",
            "echo": "testing",
        }
        if prefix in verb_map:
            return verb_map[prefix]

    tags = tool.get("tags", []) or []
    for tag in tags:
        if tag and tag not in ("read", "write", "admin", "utility"):
            return tag

    return name


def _infer_goals_from_tools(tools: list[dict[str, Any]]) -> dict[str, Goal]:
    """Infer goals from tool metadata.

    Groups tools by inferred goal name. Each goal bundles the capability
    names (which are derived from the same metadata).
    """
    goal_buckets: dict[str, dict[str, Any]] = {}

    for tool in tools:
        goal_name = _goal_name_from_tool(tool)
        cap_name = f"capability.{goal_name}"
        tool_name = tool.get("name", "")

        if goal_name not in goal_buckets:
            goal_buckets[goal_name] = {
                "name": goal_name,
                "capabilities": [],
                "tool_names": [],
                "description": tool.get("purpose", "") or tool.get("description", ""),
            }

        if cap_name not in goal_buckets[goal_name]["capabilities"]:
            goal_buckets[goal_name]["capabilities"].append(cap_name)
        if tool_name not in goal_buckets[goal_name]["tool_names"]:
            goal_buckets[goal_name]["tool_names"].append(tool_name)

    return {
        name: Goal(
            name=data["name"],
            capabilities=data["capabilities"],
            description=data.get("description", ""),
        )
        for name, data in goal_buckets.items()
    }


class GoalRegistry:
    """Auto-populated registry of user-facing goals.

    Goals are inferred from tool metadata at registration time.
    No hardcoded goal names.
    """

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}

    def register_from_tools(self, tools: list[dict[str, Any]]) -> None:
        """Register goals inferred from tool metadata."""
        self._goals = _infer_goals_from_tools(tools)
        logger.info("goal_registry.registered", count=len(self._goals))

    def get_goal(self, name: str) -> Goal | None:
        return self._goals.get(name)

    def get_goals(self) -> list[Goal]:
        return list(self._goals.values())

    def find_goals(self, query: str) -> list[tuple[Goal, float]]:
        """Find goals matching a query string by keyword scoring."""
        tokens = query.lower().split()
        scored: list[tuple[Goal, float]] = []
        for goal in self._goals.values():
            score = 0.0
            text = f"{goal.name} {goal.description} {' '.join(goal.capabilities)}".lower()
            for token in tokens:
                if token in text:
                    score += 1.0
            if score > 0:
                scored.append((goal, score / max(len(tokens), 1)))
        return sorted(scored, key=lambda x: -x[1])


_singleton_registry: GoalRegistry | None = None


def get_goal_registry() -> GoalRegistry:
    """Get the singleton GoalRegistry instance."""
    global _singleton_registry
    if _singleton_registry is None:
        _singleton_registry = GoalRegistry()
    return _singleton_registry


def populate_from_tools(tools: list[dict[str, Any]]) -> None:
    """Convenience: register goals from tool list."""
    registry = get_goal_registry()
    registry.register_from_tools(tools)
