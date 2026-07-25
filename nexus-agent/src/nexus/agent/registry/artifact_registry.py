"""Artifact Registry — typed, registered entities flowing through graph state.

Artifacts replace magic strings with typed, validated data contracts.
Every field in StructuredContext.entities can be backed by an Artifact
definition that specifies its type, schema, and lifecycle.

No hardcoded artifact names. Artifacts are either inferred from tool
input/output schemas or explicitly registered via the GoalRegistry.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ArtifactType(str, Enum):
    """Classification of an artifact by its role in the system.

    - DATA: Transient data produced/consumed by tools (e.g., coordinates, temperature)
    - STATE: Persistent system state that survives across turns
    - DECISION: A user or system choice that affects routing
    - REFERENCE: An external resource identifier (e.g., bookmark ID, session ID)
    """
    DATA = "DATA"
    STATE = "STATE"
    DECISION = "DECISION"
    REFERENCE = "REFERENCE"


class Artifact(BaseModel):
    """A typed, validated data entity that flows through the graph.

    Each artifact carries its own schema for validation, a trace_id for
    observability, and optional TTL for cache expiration.

    Attributes:
        name: Unique artifact name (e.g., "Coordinates", "WeatherForecast").
        type: Classification (DATA, STATE, DECISION, REFERENCE).
        schema_def: JSON Schema dict for value validation.
        description: Human-readable description.
        ttl: Optional cache expiration in seconds (None = no expiry).
        trace_id: Unique identifier for this artifact instance.
        created_at: ISO timestamp of creation.
    """

    name: str = Field(description="Unique artifact name")
    type: ArtifactType = Field(default=ArtifactType.DATA, description="Artifact classification")
    schema_def: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for validation",
    )
    description: str = Field(default="", description="Human-readable description")
    ttl: int | None = Field(default=None, description="Cache TTL in seconds")
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "schema": self.schema_def,
            "description": self.description,
            "ttl": self.ttl,
        }


def _infer_schema_from_properties(props: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal JSON Schema from tool property definitions."""
    return {
        "type": "object",
        "properties": props,
        "additionalProperties": True,
    }


def _infer_artifacts_from_tool(tool: dict[str, Any]) -> list[Artifact]:
    """Infer artifact definitions from a tool's input and output schemas.

    Input fields become CONSUMER artifacts.
    Output fields become PRODUCER artifacts.
    The tool name + field name becomes the artifact name.

    Example:
        Tool: get_weather
        Input: {latitude, longitude} → Artifact("get_weather.latitude"), Artifact("get_weather.longitude")
        Output: {temperature, conditions} → Artifact("get_weather.temperature"), Artifact("get_weather.conditions")
    """
    artifacts: list[Artifact] = []
    name = tool.get("name", "")
    input_schema = tool.get("input_schema", {}) or {}
    output_schema = tool.get("output_schema", {}) or {}

    for direction, schema in [("input", input_schema), ("output", output_schema)]:
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        for field_name, field_schema in props.items():
            full_name = f"{name}.{field_name}"
            atype = ArtifactType.DATA
            artifact = Artifact(
                name=full_name,
                type=atype,
                schema_def=field_schema if isinstance(field_schema, dict) else {},
                description=field_schema.get("description", "") if isinstance(field_schema, dict) else "",
            )
            artifacts.append(artifact)

    return artifacts


# ── Singleton Registry ──────────────────────────────────────────────

_singleton_registry: ArtifactRegistry | None = None


class ArtifactRegistry:
    """Registry of all known artifact definitions.

    Artifacts are inferred from tool input/output schemas at registration
    time. They can also be explicitly registered for complex workflows
    via the GoalRegistry.

    No hardcoded artifact names. All artifacts are derived from tool
    metadata or explicitly registered.
    """

    def __init__(self) -> None:
        self._artifacts: dict[str, Artifact] = {}

    def register(self, artifact: Artifact) -> None:
        self._artifacts[artifact.name] = artifact

    def register_from_tool(self, tool: dict[str, Any]) -> None:
        """Infer and register artifacts from a single tool definition."""
        for artifact in _infer_artifacts_from_tool(tool):
            self._artifacts[artifact.name] = artifact

    def register_from_tools(self, tools: list[dict[str, Any]]) -> None:
        """Infer and register artifacts from all available tools."""
        for tool in tools:
            self.register_from_tool(tool)

    def get(self, name: str) -> Artifact | None:
        return self._artifacts.get(name)

    def get_all(self) -> list[Artifact]:
        return list(self._artifacts.values())

    def find_by_field(self, field_name: str) -> list[Artifact]:
        """Find artifacts whose name ends with the given field name."""
        return [a for a in self._artifacts.values() if a.name.endswith(f".{field_name}") or a.name == field_name]


def get_artifact_registry() -> ArtifactRegistry:
    """Get the singleton ArtifactRegistry instance."""
    global _singleton_registry
    if _singleton_registry is None:
        _singleton_registry = ArtifactRegistry()
    return _singleton_registry
