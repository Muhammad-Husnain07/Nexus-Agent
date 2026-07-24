"""IntentRegistry — dynamically resolves intents from registered tools.

No hardcoded intents. Every intent is derived from the tool's purpose
and input_schema at registration time. Tools register themselves.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from nexus.tools.keywords import extract_keywords, tokenize

logger = structlog.get_logger("nexus.agent.registry.intent_registry")


class IntentSchema:
    """Schema for a single intent — derived from a tool's metadata."""

    def __init__(
        self,
        name: str,
        description: str,
        required_fields: list[str],
        optional_fields: list[str],
        defaults: dict[str, Any],
        tool_mapping: list[str],
        validators: dict[str, callable] | None = None,
    ):
        self.name = name
        self.description = description
        self.required_fields = required_fields
        self.optional_fields = optional_fields
        self.defaults = defaults
        self.tool_mapping = tool_mapping
        self.validators = validators or {}


# Fast built-in validators (no LLM needed)
BUILTIN_VALIDATORS: dict[str, callable] = {
    "latitude": lambda v: isinstance(v, (int, float)) and -90 <= v <= 90,
    "longitude": lambda v: isinstance(v, (int, float)) and -180 <= v <= 180,
    "url": lambda v: isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")),
    "email": lambda v: isinstance(v, str) and "@" in v and "." in v.split("@")[-1],
    "positive_int": lambda v: isinstance(v, int) and v > 0,
    "non_empty_string": lambda v: isinstance(v, str) and len(v.strip()) > 0,
}


def _infer_validators(param_name: str, param_schema: dict[str, Any]) -> dict[str, callable]:
    """Infer validators from parameter name and schema — no hardcoding."""
    validators: dict[str, callable] = {}
    name_lower = param_name.lower()

    for rule_name, validator in BUILTIN_VALIDATORS.items():
        if rule_name in name_lower:
            validators[rule_name] = validator

    param_type = param_schema.get("type")
    if param_type == "integer":
        validators["type_int"] = lambda v: isinstance(v, int)
    elif param_type == "number":
        validators["type_number"] = lambda v: isinstance(v, (int, float))
    elif param_type == "boolean":
        validators["type_bool"] = lambda v: isinstance(v, bool)

    min_val = param_schema.get("minimum")
    max_val = param_schema.get("maximum")
    if min_val is not None:
        validators["min"] = lambda v: v >= min_val
    if max_val is not None:
        validators["max"] = lambda v: v <= max_val

    return validators


def _build_intent_schema(tool: dict[str, Any]) -> IntentSchema:
    """Build an IntentSchema from a tool definition dynamically."""
    name = tool.get("name", "")
    purpose = tool.get("purpose", "") or tool.get("description", "")

    input_schema = tool.get("input_schema", {})
    properties = input_schema.get("properties", {})
    required = input_schema.get("required", [])

    optional = [k for k in properties if k not in required]

    defaults: dict[str, Any] = {}
    for k, v in properties.items():
        if "default" in v:
            defaults[k] = v["default"]

    # Infer validators from schemas
    validators: dict[str, callable] = {}
    for param_name, param_schema in properties.items():
        inferred = _infer_validators(param_name, param_schema)
        validators.update(inferred)

    return IntentSchema(
        name=name,
        description=purpose,
        required_fields=required,
        optional_fields=optional,
        defaults=defaults,
        tool_mapping=[name],
        validators=validators,
    )


def _build_intent_name(tool_name: str) -> str:
    """Derive a human-readable intent name from the tool name.

    ``get_weather`` → ``"get_weather"`` (direct tool intent name)
    We keep it as the tool name since the LLM understands it directly.
    """
    return tool_name


def _build_intent_purpose(tool: dict[str, Any]) -> str:
    """Build an intent description from tool metadata."""
    parts = [
        tool.get("purpose", ""),
        tool.get("description", ""),
    ]
    return ". ".join(p for p in parts if p)


class IntentRegistry:
    """Central registry for intents — dynamically populated from tools.

    Tools register themselves via ``register_from_tool()``, which extracts
    required fields, optional fields, defaults, and validators from the tool's
    input_schema automatically. No hardcoded intent definitions.
    """

    def __init__(self):
        self._schemas: dict[str, IntentSchema] = {}
        self._tool_to_intent: dict[str, str] = {}

    def register_from_tool(self, tool: dict[str, Any]) -> str | None:
        """Register an intent derived from a tool's metadata.

        Returns the intent name, or None if the tool can't be mapped.
        """
        name = tool.get("name", "")
        if not name:
            return None

        # Skip utility/test tools that don't represent user-facing intents
        tags = tool.get("tags", [])
        if "test" in tags and "utility" in tags:
            return None

        schema = _build_intent_schema(tool)
        intent_name = _build_intent_name(name)

        self._schemas[intent_name] = schema
        self._tool_to_intent[name] = intent_name

        logger.debug("intent_registry.registered", intent=intent_name, tool=name)
        return intent_name

    def register_from_tools(self, tools: list[dict[str, Any]]) -> int:
        """Register intents from a list of tools.

        Returns the number of intents registered.
        """
        count = 0
        for tool in tools:
            if self.register_from_tool(tool):
                count += 1
        logger.info("intent_registry.populated", count=count, total=len(tools))
        return count

    def get_schema(self, intent: str) -> IntentSchema | None:
        """Get the schema for a given intent."""
        return self._schemas.get(intent)

    def get_intents(self) -> list[str]:
        """Return all registered intent names."""
        return list(self._schemas.keys())

    def get_tools_for_intent(self, intent: str) -> list[str]:
        """Return tool names that satisfy this intent."""
        schema = self._schemas.get(intent)
        if schema:
            return schema.tool_mapping
        return []

    def validate_entities(self, intent: str, entities: dict[str, Any]) -> list[str]:
        """Pure Python validation — checks required fields + validators.

        Returns a list of missing or invalid field names.
        Returns ["unknown_intent"] if the intent isn't registered.
        """
        schema = self._schemas.get(intent)
        if not schema:
            return ["unknown_intent"]

        missing = []

        # Check required fields
        for field in schema.required_fields:
            if field not in entities or entities[field] is None:
                missing.append(field)
                continue

            value = entities[field]
            # Run validators for this field
            for vname, validator in schema.validators.items():
                # Check if validator applies to this field
                if vname in field.lower():
                    try:
                        if not validator(value):
                            missing.append(f"{field}_invalid")
                    except (TypeError, ValueError):
                        missing.append(f"{field}_invalid")

        return missing

    def apply_defaults(self, intent: str, entities: dict[str, Any]) -> dict[str, Any]:
        """Apply default values for optional fields that are missing."""
        schema = self._schemas.get(intent)
        if not schema:
            return entities

        result = dict(entities)
        for field, default in schema.defaults.items():
            if field not in result or result[field] is None:
                result[field] = default

        return result

    def resolve_intent(self, intent: str, entities: dict[str, Any]) -> dict[str, Any]:
        """Full resolution: validate + apply defaults + return execution request.

        Returns a validated execution request dict with:
        - intent: the matched intent name
        - entities: validated + defaulted entities
        - tools: tool names to execute
        - missing: list of missing fields (empty if ready to execute)
        """
        missing = self.validate_entities(intent, entities)
        resolved_entities = self.apply_defaults(intent, entities)
        tools = self.get_tools_for_intent(intent)

        return {
            "intent": intent,
            "entities": resolved_entities,
            "tools": tools,
            "missing": missing,
            "ready": len(missing) == 0,
        }


# Singleton
_registry: IntentRegistry | None = None


def get_registry() -> IntentRegistry:
    """Get or create the singleton IntentRegistry."""
    global _registry
    if _registry is None:
        _registry = IntentRegistry()
    return _registry


def populate_from_tools(tools: list[dict[str, Any]]) -> int:
    """Convenience: populate the registry from a list of tools.

    Called by the runner when tools are loaded.
    """
    registry = get_registry()
    return registry.register_from_tools(tools)
