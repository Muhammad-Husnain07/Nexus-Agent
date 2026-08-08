"""LLVM-style Pass Manager — dynamically loads and runs optimization passes on ExecutionGraphs.

Each pass is a module in ``passes/`` with a ``run(graph: ExecutionGraph) -> ExecutionGraph``
signature for sync passes, or ``async run(graph, **kwargs)`` for async passes
(like ``InputEnrichmentPass`` which needs DB access).

Passes are discovered dynamically — no hardcoded pass list.

The fixpoint iteration limit comes from ``settings.compiler.max_fixpoint_iterations``.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import pkgutil
from typing import Any

import structlog

from nexus.compiler.ir_models import ExecutionGraph, GraphSnapshot, OptimizationReport
from nexus.config.settings import get_settings as _pm_settings

logger = structlog.get_logger("nexus.compiler.pass_manager")


def _discover_passes() -> list[str]:
    """Discover all pass modules in the ``passes`` package.

    Returns module names ordered by optional module-level ``PRIORITY``
    (lower runs first), falling back to alphabetical order for passes that
    declare none. No hardcoded pass list — full dynamic discovery.
    """
    import nexus.compiler.passes as passes_pkg

    modules = []
    for _importer, modname, ispkg in pkgutil.iter_modules(passes_pkg.__path__):
        if not ispkg:
            modules.append(modname)

    def _sort_key(modname: str) -> tuple[int, str]:
        try:
            mod = importlib.import_module(f"nexus.compiler.passes.{modname}")
            priority = getattr(mod, "PRIORITY", 100)
        except Exception:
            priority = 100
        return (int(priority) if priority is not None else 100, modname)

    return sorted(modules, key=_sort_key)


def _load_pass(modname: str) -> Any | None:
    """Load a pass module and return its ``run`` function.

    Returns None if the module has no ``run`` function with the correct signature.
    """
    try:
        mod = importlib.import_module(f"nexus.compiler.passes.{modname}")
        if not hasattr(mod, "run"):
            logger.debug("pass_manager.skip_no_run", mod=modname)
            return None
        fn = mod.run
        if not callable(fn):
            return None
        sig = inspect.signature(fn)
        if len(sig.parameters) < 1:
            return None
        return fn
    except Exception as exc:
        logger.warning("pass_manager.load_failed", mod=modname, error=str(exc))
        return None


def _is_async(fn: Any) -> bool:
    """Check if a pass function is async."""
    return asyncio.iscoroutinefunction(fn)


def _hash_graph(graph: ExecutionGraph) -> str:
    """Pure: compute SHA256 of the serialized graph for fixpoint detection."""
    raw = graph.model_dump_json()
    return hashlib.sha256(raw.encode()).hexdigest()


def optimize(
    graph: ExecutionGraph,
) -> tuple[ExecutionGraph, list[GraphSnapshot]]:
    """Run all discovered sync optimization passes with fixpoint iteration.

    Pure: no I/O, no datetime, no random. For async passes (InputEnrichment),
    use ``optimize_async()`` instead.
    """
    return _run_optimize(graph, {})


async def optimize_async(
    graph: ExecutionGraph,
    pass_kwargs: dict[str, Any] | None = None,
) -> tuple[ExecutionGraph, list[GraphSnapshot]]:
    """Run all optimization passes with fixpoint iteration, supporting async passes.

    Args:
        graph: The initial ``ExecutionGraph`` to optimize.
        pass_kwargs: Extra keyword arguments forwarded to async pass ``run()``
            functions (e.g. ``{"registry": ..., "user_preferences": ...}``).

    Returns:
        A tuple of (final ``ExecutionGraph``, list of ``GraphSnapshot`` for observability).
    """
    return await _run_optimize_async(graph, pass_kwargs or {})


def _max_iterations() -> int:
    """Get max fixpoint iterations from settings."""
    try:
        return _pm_settings().compiler.max_fixpoint_iterations
    except Exception:
        return 5


def _run_optimize(
    graph: ExecutionGraph,
    _pass_kwargs: dict[str, Any],
) -> tuple[ExecutionGraph, list[GraphSnapshot]]:
    """Sync path — for passes that are pure (no I/O)."""
    passes = _discover_passes()
    if not passes:
        logger.info("pass_manager.no_passes_found")
        return graph, []

    current = graph
    snapshots: list[GraphSnapshot] = [
        GraphSnapshot(version=1, graph=current.model_copy(deep=True), pass_name="initial"),
    ]
    max_iter = _max_iterations()

    for iteration in range(max_iter):
        before_hash = _hash_graph(current)
        before_count = len(current.nodes)
        transformations: list[str] = []

        for modname in passes:
            fn = _load_pass(modname)
            if fn is None:
                continue
            if _is_async(fn):
                continue  # skip async passes in sync path

            try:
                new_graph = fn(current.model_copy(deep=True))
                if new_graph is not None:
                    current = new_graph
                    after_count = len(current.nodes)
                    if after_count != before_count:
                        transformations.append(f"{modname}: {before_count}→{after_count} nodes")
                    logger.debug("pass_manager.run_ok", mod=modname, nodes=after_count)
            except Exception as exc:
                logger.warning("pass_manager.run_failed", mod=modname, error=str(exc))

        after_hash = _hash_graph(current)
        snapshots.append(GraphSnapshot(
            version=len(snapshots) + 1,
            graph=current.model_copy(deep=True),
            pass_name=f"iteration_{iteration + 1}",
            report=OptimizationReport(
                pass_name=f"iteration_{iteration + 1}",
                transformations=transformations,
                nodes_before=before_count,
                nodes_after=len(current.nodes),
            ),
        ))
        if after_hash == before_hash:
            logger.info("pass_manager.fixpoint_reached", iteration=iteration + 1)
            break

    logger.info("pass_manager.complete", iterations=min(iteration + 1, max_iter), snapshots=len(snapshots), final_nodes=len(current.nodes))
    return current, snapshots


async def _run_optimize_async(
    graph: ExecutionGraph,
    pass_kwargs: dict[str, Any],
) -> tuple[ExecutionGraph, list[GraphSnapshot]]:
    """Async path — supports passes that need I/O (like InputEnrichment)."""
    passes = _discover_passes()
    if not passes:
        logger.info("pass_manager.no_passes_found")
        return graph, []

    current = graph
    snapshots: list[GraphSnapshot] = [
        GraphSnapshot(version=1, graph=current.model_copy(deep=True), pass_name="initial"),
    ]
    max_iter = _max_iterations()

    for iteration in range(max_iter):
        before_hash = _hash_graph(current)
        before_count = len(current.nodes)
        transformations: list[str] = []

        for modname in passes:
            fn = _load_pass(modname)
            if fn is None:
                continue

            try:
                if _is_async(fn):
                    new_graph = await fn(current.model_copy(deep=True), **pass_kwargs)
                else:
                    new_graph = fn(current.model_copy(deep=True))

                if new_graph is not None:
                    current = new_graph
                    after_count = len(current.nodes)
                    if after_count != before_count:
                        transformations.append(f"{modname}: {before_count}→{after_count} nodes")
                    logger.debug("pass_manager.run_ok", mod=modname, nodes=after_count)
            except Exception as exc:
                logger.warning("pass_manager.run_failed", mod=modname, error=str(exc))

        after_hash = _hash_graph(current)
        snapshots.append(GraphSnapshot(
            version=len(snapshots) + 1,
            graph=current.model_copy(deep=True),
            pass_name=f"iteration_{iteration + 1}",
            report=OptimizationReport(
                pass_name=f"iteration_{iteration + 1}",
                transformations=transformations,
                nodes_before=before_count,
                nodes_after=len(current.nodes),
            ),
        ))
        if after_hash == before_hash:
            logger.info("pass_manager.fixpoint_reached", iteration=iteration + 1)
            break

    logger.info("pass_manager.complete", iterations=min(iteration + 1, max_iter), snapshots=len(snapshots), final_nodes=len(current.nodes))
    return current, snapshots
