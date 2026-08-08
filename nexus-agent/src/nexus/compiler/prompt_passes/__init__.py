"""Prompt IR optimization passes — operate on ContextIR, not ExecutionGraph.

These passes are topologically sorted by their ``requires``/``produces``
declarations.  No isinstance() checks in the execution loop.

This package is separate from ``compiler/passes/`` which operates on
ExecutionGraph/DAG optimization.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from nexus.compiler.context_ir import ContextIR


class CompilerPass(ABC):
    """Base class for ContextIR optimization passes.

    Attributes:
        name: Unique pass name for dependency resolution.
        requires: List of pass names that must run before this one.
        produces: List of capability names this pass satisfies.
    """

    name: str = ""
    requires: list[str] = []
    produces: list[str] = []

    @abstractmethod
    def run(self, ir: ContextIR, metrics: dict[str, Any], **kwargs: Any) -> tuple[ContextIR, dict[str, Any]]:
        """Execute this pass on the given ContextIR.

        Args:
            ir: The current ContextIR to transform.
            metrics: Accumulated metrics dict (mutated in place).
            **kwargs: Pass-specific keyword arguments.

        Returns:
            (transformed_ir, updated_metrics) tuple.
        """
