"""Dynamic artifact type registry — no hardcoded field names.

New artifact types can be registered at runtime by any tool or node
without requiring schema changes.  The registry maps ``type`` strings
to optional Pydantic model validators (``extra="allow"`` so unknown
fields are silently accepted). Unregistered types get a dynamic
passthrough model automatically — no pre-registration needed.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# Global registry: type_str -> Pydantic model class (or None = passthrough)
_ARTIFACT_TYPE_REGISTRY: dict[str, type[BaseModel] | None] = {}


def register_artifact_type(type_str: str, model: type[BaseModel] | None = None) -> None:
    """Register a Pydantic model for a given artifact type.

    If ``model`` is ``None``, the type is registered as a passthrough
    (accepts any fields via ``extra="allow"``).
    """
    _ARTIFACT_TYPE_REGISTRY[type_str] = model


def get_artifact_model(type_str: str) -> type[BaseModel]:
    """Return the Pydantic model for the given type, or a dynamic passthrough.

    If the type is not registered, creates and caches a dynamic model
    with ``extra="allow"`` so no schema registration is required.
    """
    existing = _ARTIFACT_TYPE_REGISTRY.get(type_str)
    if existing is not None:
        return existing
    if type_str in _ARTIFACT_TYPE_REGISTRY:
        # Registered as None -> passthrough already exists
        return _PassthroughModel

    # Create a dynamic passthrough model for this type
    model = _make_passthrough_model(type_str)
    _ARTIFACT_TYPE_REGISTRY[type_str] = model
    return model


def list_registered_types() -> list[str]:
    """Return all registered artifact type strings."""
    return list(_ARTIFACT_TYPE_REGISTRY.keys())


# ============================================================================
# Passthrough models
# ============================================================================


class _PassthroughModel(BaseModel):
    """Generic passthrough that accepts any fields."""
    model_config = ConfigDict(extra="allow")


def _make_passthrough_model(type_str: str) -> type[BaseModel]:
    """Create a dynamic passthrough model for an unregistered type."""
    import pydantic

    # Use create_model to make a dynamic type with the type_str as class name
    sanitized = type_str.replace("-", "_").replace(" ", "_").title()
    namespace = {"model_config": ConfigDict(extra="allow")}
    return type(sanitized, (BaseModel,), namespace)
