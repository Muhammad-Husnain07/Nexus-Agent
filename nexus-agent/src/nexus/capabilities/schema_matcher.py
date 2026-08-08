"""SchemaMatcher — compares required input shapes against available inputs.

Used by DynamicCapabilityResolver to score how well an endpoint's declared
input policy matches the caller's actual inputs.

Pure functions — no I/O, no side effects.
"""

from __future__ import annotations

from typing import Any

from nexus.db.models.registry import EndpointModel


class SchemaMatcher:
    """Compares endpoint input expectations against actual caller inputs.

    The endpoint's required inputs are inferred from its ``input_schema``
    (which has a JSON Schema ``properties`` dict).  The caller's actual
    shape is the dict of keys they provide.
    """

    @staticmethod
    def compute(
        endpoint: EndpointModel,
        inputs_shape: dict[str, Any],
    ) -> float:
        """Compute a schema match score.

        Args:
            endpoint: The endpoint to evaluate.
            inputs_shape: Dict of keys the caller provides (may be empty).

        Returns:
            1.0 if all required keys are present, 0.5 for partial overlap,
            0.0 if no overlap at all.
        """
        required_keys: set[str] = set()
        for cap in (endpoint.provider.capability if endpoint.provider else None,):
            if cap is None:
                continue
            consumed = getattr(cap, "consumes", None) or []
            required_keys.update(consumed)

        if not required_keys:
            return 1.0

        caller_keys = set(inputs_shape.keys()) if inputs_shape else set()
        if not caller_keys:
            return 0.5

        overlap = required_keys & caller_keys
        if overlap == required_keys:
            return 1.0
        if overlap:
            return 0.5
        return 0.0
