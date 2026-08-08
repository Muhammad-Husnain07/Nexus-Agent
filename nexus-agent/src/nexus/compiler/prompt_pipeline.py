"""CompilerPipeline — topologically sorts and executes ContextIR passes.

Passes declare ``requires`` and ``produces`` as string identifiers.
The pipeline builds a DAG and executes via topological sort — no
``isinstance()`` checks in the execution loop.

Passes are discovered DYNAMICALLY from the ``prompt_passes`` package
(``pkgutil.iter_modules``) — no hardcoded pass list. Each pass may
declare a class-level ``accepts`` mapping of optional kwarg names it
consumes; the pipeline injects only those kwargs (no name-based dispatch).
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import pkgutil
from dataclasses import dataclass
from typing import Any

from nexus.compiler.context_ir import ContextIR, ContextPolicy
from nexus.compiler.prompt_cache import PromptCache
from nexus.compiler.prompt_passes import CompilerPass
from nexus.artifacts.renderers.registry import RendererRegistry


@dataclass
class PipelineResult:
    """Result of running the compiler pipeline on a ContextIR.

    Attributes:
        ir: The (possibly transformed) ContextIR after all passes.
        metrics: Accumulated pass metrics for observability.
        cache_hit: True if the result came from prompt cache.
        cached_prompt: The cached prompt messages (if cache_hit).
    """
    ir: ContextIR
    metrics: dict[str, Any]
    cache_hit: bool
    cached_prompt: list[dict] | None = None


def _discover_passes() -> list[type[CompilerPass]]:
    """Discover all prompt pass classes in the ``prompt_passes`` package.

    Returns classes sorted deterministically (priority then name). No
    hardcoded pass list — adding a new pass module registers it.
    """
    import nexus.compiler.prompt_passes as passes_pkg

    classes: list[type[CompilerPass]] = []
    for _importer, modname, ispkg in pkgutil.iter_modules(passes_pkg.__path__):
        if ispkg or modname.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"nexus.compiler.prompt_passes.{modname}")
        except Exception:
            continue
        for _name, obj in vars(mod).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, CompilerPass)
                and obj is not CompilerPass
                and getattr(obj, "name", "")
            ):
                classes.append(obj)

    def _sort_key(cls: type[CompilerPass]) -> tuple[int, str]:
        priority = getattr(cls, "PRIORITY", 100)
        return (int(priority) if priority is not None else 100, cls.name)

    return sorted(classes, key=_sort_key)


class CompilerPipeline:
    """Topologically sorted pipeline of ContextIR optimization passes.

    Usage::
        pipeline = CompilerPipeline(budget_policy, prompt_cache)
        result = await pipeline.run(ir, policy, estimator, renderer)
    """

    def __init__(self, prompt_cache: PromptCache, budget_policy: Any | None = None) -> None:
        discovered = [cls() for cls in _discover_passes()]
        if not discovered:
            # Fail loudly rather than silently serving unoptimized prompts
            raise RuntimeError("No prompt passes discovered — compiler pipeline is empty")
        # Topologically order ONCE at construction so `run()` executes passes
        # in dependency order (requires/produces), not discovery order.
        self._passes = self._topological_sort(discovered)
        self._prompt_cache = prompt_cache

    def _topological_sort(self, passes: list[CompilerPass]) -> list[CompilerPass]:
        """Sort passes by their ``requires`` declarations.

        Raises:
            ValueError: If a cyclic dependency is detected.
        """
        sorted_passes: list[CompilerPass] = []
        remaining = list(passes)
        while remaining:
            found = False
            for p in remaining:
                if not p.requires or all(req in [pp.name for pp in sorted_passes] for req in p.requires):
                    sorted_passes.append(p)
                    remaining.remove(p)
                    found = True
                    break
            if not found:
                raise ValueError("Cyclic dependency in compiler passes")
        return sorted_passes

    @staticmethod
    def _pass_kwargs(p: CompilerPass, **available: Any) -> dict[str, Any]:
        """Inject only the kwargs a pass declares in its ``accepts`` mapping.

        No name-based dispatch — the pass's own contract drives injection.
        """
        accepts = getattr(p, "accepts", None) or {}
        if not isinstance(accepts, dict):
            return {}
        return {k: available[k] for k in accepts if k in available}

    async def run(
        self,
        ir: ContextIR,
        policy: ContextPolicy,
        estimator: Any,
        renderer: Any,
        cancellation_token: asyncio.Event | None = None,
        use_cache: bool = True,
    ) -> PipelineResult:
        """Execute the pipeline, returning the transformed ContextIR.

        Args:
            ir: The input ContextIR.
            policy: Selection/pruning policy.
            estimator: Token estimator for compression pass.
            renderer: Prompt renderer for compression pass.
            cancellation_token: Optional cancellation event.
            use_cache: If True, check and populate prompt cache.

        Returns:
            PipelineResult with the final IR and metrics.
        """
        if cancellation_token and cancellation_token.is_set():
            raise asyncio.CancelledError()

        # Check cache
        fp = ir.fingerprint(RendererRegistry.version_hash())
        if use_cache:
            cached = self._prompt_cache.get(fp, ir.model_name, ir.budget_limit)
            if cached is not None:
                return PipelineResult(ir, {"cache_hit": True}, True, cached)

        metrics: dict[str, Any] = {"cache_hit": False}
        current_ir = ir

        available_kwargs: dict[str, Any] = {
            "policy": policy,
            "estimator": estimator,
            "renderer": renderer,
        }

        # Execute passes in topological order
        sorted_passes = self._topological_sort(self._passes)
        for p in sorted_passes:
            if cancellation_token and cancellation_token.is_set():
                raise asyncio.CancelledError()

            extra_kwargs = self._pass_kwargs(p, **available_kwargs)
            current_ir, metrics = p.run(current_ir, metrics, **extra_kwargs)

        return PipelineResult(current_ir, metrics, False)
