"""Generic ``@context_node`` decorator — enforces ``Context(v) → Context(v+1)`` immutability.

Every graph node is wrapped so it receives an ``ExecutionContext`` and returns
a ``StatePatch``. The wrapper handles the bidirectional mapping between LangGraph's
AgentState dict and the immutable ExecutionContext automatically.

Usage — in ``graph.py``::

    from nexus.agent.node_wrapper import context_node

    @context_node
    async def my_node(ctx: ExecutionContext, tool_executor: ToolExecutor) -> StatePatch:
        ...

The decorator **dynamically detects** whether the decorated function expects the
new ``ctx: ExecutionContext`` pattern or the old ``state: AgentState`` pattern
by inspecting the first parameter's type annotation.

- If annotated as ``ExecutionContext`` → full Context(v) → Context(v+1) enforcement.
- If annotated as anything else (or unannotated) → backward-compat pass-through.

No per-node boilerplate. No hardcoded field names.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from nexus.execution.context import (
    ExecutionContext,
    StatePatch,
    _is_global_or_session_key,
    _STATIC_STRIP_FIELDS,
)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def _expects_context(func: Callable[..., Any]) -> bool:
    """Check if the first parameter is typed as ExecutionContext (new pattern).

    Handles both string annotations (``from __future__ import annotations``)
    and direct class annotations (no ``from __future__``).
    """
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    if not params:
        return False
    first_param = params[0]
    ann = first_param.annotation
    if ann is inspect.Parameter.empty:
        return False
    # String annotation (from __future__ import annotations)
    ctx_name = "ExecutionContext"
    if isinstance(ann, str):
        return ann == ctx_name
    # Direct class annotation
    return ann is ExecutionContext


def context_node(func: F) -> F:
    """Decorate an agent node to enforce Context(v) → Context(v+1) immutability.

    **New pattern** (``ctx: ExecutionContext`` as first param)::

        1. Builds an ``ExecutionContext`` from the incoming AgentState dict.
        2. Calls ``func(ctx, **bound_deps)`` — expects ``StatePatch`` return.
        3. Applies the patch to produce ``Context(v+1)``.
        4. Serialises back to an AgentState-compatible dict via ``to_state_update()``.

    **Old pattern** (any other first param — backward compat)::

        The wrapper passes ``state`` through unchanged. No immutability enforcement.
    """

    expects_ctx = _expects_context(func)

    @functools.wraps(func)
    async def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        if not expects_ctx:
            # Backward-compat pass-through
            result = await func(state, *args, **kwargs)
            if isinstance(result, StatePatch):
                ctx = ExecutionContext.from_state(state)
                return ctx.apply(result).to_state_update()
            return result if isinstance(result, dict) else {}

        # New pattern: build Context, call node, apply patch
        ctx = ExecutionContext.from_state(state)
        ctx.record_node(func.__name__)  # Append node name to timeline BEFORE execution
        result = await func(ctx, *args, **kwargs)

        if isinstance(result, StatePatch):
            patch = result
        elif isinstance(result, dict):
            # Backward-compat shim: plain dict becomes StatePatch(updates=...)
            patch = StatePatch(version=ctx.version + 1, updates=result)
        else:
            raise TypeError(
                f"@{func.__name__} must return StatePatch or dict, got {type(result).__name__}",
            )

        # Guard: reject StatePatch keys that belong to GlobalContext or SessionContext
        for key in list(patch.updates.keys()) + patch.removes:
            if _is_global_or_session_key(key):
                raise ValueError(
                    f"@{func.__name__} attempted to set GlobalContext/SessionContext "
                    f"key '{key}' via StatePatch — forbidden",
                )

        new_ctx = ctx.apply(patch)

        # Merge: canonical context update + flat routing keys from the patch
        merged = new_ctx.to_state_update()

        # Strip banned fields from patch.updates BEFORE merging (prevents
        # tool_results/_executor_results from re-entering the snapshot)
        stripped_updates = {
            k: v for k, v in patch.updates.items()
            if k not in _STATIC_STRIP_FIELDS
        }
        merged.update(stripped_updates)

        # Surface _context_snapshot fields to the top level so downstream
        # nodes can read them via state.get(key, default) even when they
        # were set by a previous @context_node via StatePatch.updates.
        # Without this, fields like _critique_rounds, _requires_refinement
        # get buried inside _context_snapshot and reset to defaults on
        # the next node invocation, breaking state-carrying loops.
        cs = merged.get("_context_snapshot")
        if isinstance(cs, dict):
            for k, v in cs.items():
                if k not in merged:
                    merged[k] = v
        return merged

    return wrapper  # type: ignore[return-value]
