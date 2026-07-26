"""Semantic Planner Node — translates natural language to a LogicalWorkflow via LLM.

This is the ONLY LLM call in the critical path that produces structured output.
It receives the Capability Catalog from the DB (logical op names) and uses
``instructor`` to force the LLM to emit a validated ``LogicalWorkflow``.

The LLM is structurally barred from outputting invalid capability names via
a dynamically generated Pydantic ``Literal`` type.  ``instructor`` auto-retries
up to 3 times if the LLM attempts an invalid ``op`` value.

If ``instructor`` is unavailable, falls back to
``response_format={"type": "json_object"}`` with manual validation.

Returns a ``StatePatch`` with ``_logical_workflow`` set.  On parse failure,
returns an error patch.
"""

from __future__ import annotations

import json
import typing
import time
from typing import Any

import structlog
from pydantic import ValidationError, create_model

from nexus.agent.node_wrapper import context_node
from nexus.compiler.cache import get_parse_cache
from nexus.compiler.ir_models import LogicalNode, LogicalWorkflow
from nexus.config.settings import get_settings
from nexus.execution.context import ExecutionContext, StatePatch
from nexus.execution.event_emitter import emit_planning_completed
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.semantic_planner")

try:
    from nexus.config.settings import get_settings as _sp_settings
    _SP_MAX_NODES = _sp_settings().compiler.max_workflow_nodes
except Exception:
    _SP_MAX_NODES = 50


# ============================================================================
# Capability catalog — fetched from DB at runtime
# ============================================================================


async def _fetch_capabilities() -> tuple[list[str], str]:
    """Fetch all enabled capabilities from the DB.

    Returns:
        A tuple of ``(valid_ops, catalog_string)`` where ``valid_ops`` is
        the list of exact ``logical_op_name`` values for the ``Literal``
        type, and ``catalog_string`` is the human-readable prompt catalog.
    """
    from nexus.db.base import async_session as _cat_db
    from nexus.registry.client import RegistryClient

    valid_ops: list[str] = []
    catalog_parts: list[str] = []

    try:
        async with _cat_db() as session:
            registry = RegistryClient(session)
            capabilities = await registry.get_all_capabilities()

            for cap in capabilities:
                name = cap.logical_op_name or cap.name
                if not name:
                    continue
                valid_ops.append(name)

                hints = ""
                policy = cap.input_policy or {}
                defaults = policy.get("defaults", {})
                if defaults:
                    hints = ", ".join(defaults.keys())

                catalog_parts.append(f"{name} (inputs: {hints})" if hints else name)
    except Exception as exc:
        logger.warning("semantic_planner.catalog_db_failed", error=str(exc))

    catalog = "Available capabilities: " + ", ".join(catalog_parts) if catalog_parts else ""
    return valid_ops, catalog


# ============================================================================
# Instructor-backed LLM extraction with strict Literal enforcement
# ============================================================================


async def _instructor_extract(
    prompt: str,
    user_message: str,
    llm: LLMClient,
    model: str,
    session_settings: Any,
    valid_ops: list[str],
) -> dict[str, Any] | None:
    """Use ``instructor`` to extract a validated ``LogicalWorkflow`` from the LLM.

    Dynamically builds a Pydantic model with ``op: Literal[valid_ops]``,
    structurally barring the LLM from outputting invalid capability names.
    ``instructor.max_retries=3`` feeds validation errors back to the LLM for
    self-correction.

    Returns a dict version of the LogicalWorkflow, or ``None`` on failure.
    """
    import importlib
    import os

    try:
        import openai as _openai

        provider, provider_name = llm.registry.resolve_provider(model)
        base_url = provider.config.base_url or ""
        api_key_ref = provider.config.api_key_ref or ""
        api_key = os.environ.get(api_key_ref, "") if api_key_ref else ""

        instructor_mod = importlib.import_module("instructor")
        from_openai = getattr(instructor_mod, "from_openai", None)
        if from_openai is None:
            return None

        client = from_openai(
            _openai.AsyncOpenAI(base_url=base_url, api_key=api_key),
            mode=instructor_mod.Mode.JSON_SCHEMA,
        )

        clean_model = model.split("/", 1)[-1] if "/" in model else model

        # Build StrictLogicalNode with Literal[valid_ops] for the "op" field
        if valid_ops:
            op_literal = typing.Literal[tuple(valid_ops)]  # type: ignore
            StrictLogicalNode = create_model(
                "StrictLogicalNode",
                op=(op_literal, ...),
                __base__=LogicalNode,
            )
            StrictLogicalWorkflow = create_model(
                "StrictLogicalWorkflow",
                nodes=(list[StrictLogicalNode], ...),
                __base__=LogicalWorkflow,
            )
        else:
            StrictLogicalWorkflow = LogicalWorkflow

        workflow: LogicalWorkflow = await client.chat.completions.create(
            model=clean_model,
            response_model=StrictLogicalWorkflow,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=max(session_settings.extraction_max_tokens or 1024, 2048),
            max_retries=3,
        )
        return workflow.model_dump()
    except Exception as exc:
        logger.warning("semantic_planner.instructor_failed", error=str(exc))
        return None


async def _json_extract(
    prompt: str,
    user_message: str,
    llm: LLMClient,
    model: str,
    settings: Any,
) -> dict[str, Any] | None:
    """Fallback: use ``response_format=json_object`` with manual JSON parsing."""
    import re

    total_cost: float = 0.0
    total_tokens: int = 0

    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            max_tokens=settings.extraction_max_tokens,
            response_format={"type": "json_object"},
        )

        if hasattr(response, "usage") and response.usage:
            total_tokens = getattr(response.usage, "total_tokens", 0) or 0

        content = response.content or "{}"
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n```$", "", content)

        parsed = json.loads(content)
        if isinstance(parsed, list):
            parsed = {"version": "1.0", "nodes": parsed, "collections": {}}

        if not isinstance(parsed, dict) or "nodes" not in parsed:
            parsed = {"version": "1.0", "nodes": [], "collections": {}}

        try:
            LogicalWorkflow.model_validate(parsed)
        except ValidationError as ve:
            logger.warning("semantic_planner.schema_mismatch", errors=ve.errors())

        return parsed
    except Exception as exc:
        logger.error("semantic_planner.json_extract_failed", error=str(exc))
        return None


# ============================================================================
# Conversation history formatter
# ============================================================================


def _format_history(messages: list) -> str:
    """Format prior conversation turns for anaphora resolution.

    Shows up to 3 prior exchanges (6 prior messages), excluding the
    current user message which is sent separately to the LLM.
    The LLM uses this to resolve pronouns and contextual references.
    """
    # Exclude the last message (current user query) from history
    prior = messages[:-1] if len(messages) > 1 else []
    recent = prior[-6:] if len(prior) > 6 else prior
    lines = []
    for msg in recent:
        if isinstance(msg, dict):
            role = msg.get("role", "unknown").capitalize()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


# ============================================================================
# Graph node
# ============================================================================


@context_node
async def semantic_parser_node(
    ctx: ExecutionContext,
    llm: LLMClient,
    model: str,
) -> StatePatch:
    """Translate the user message into a LogicalWorkflow via LLM.

    1. Fetch capabilities from DB (``valid_ops`` list + prompt catalog).
    2. Check ParseCache — if hit, return cached LogicalWorkflow (no LLM).
    3. If miss, make ONE LLM call with ``instructor`` and strict ``Literal``.
    4. Store in ParseCache for future hits.
    """
    snapshot = ctx.snapshot
    messages = snapshot.get("messages", [])
    last_message = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_message = str(m.get("content", ""))
            break
        if hasattr(m, "role") and getattr(m, "role") == "user":
            last_message = str(getattr(m, "content", ""))
            break

    if not last_message:
        return StatePatch(
            version=ctx.version + 1,
            updates={
                "_logical_workflow": None,
                "_extraction_result": {},
            },
        )

    # Fetch capabilities from DB: both the Literal-valid list and the prompt catalog
    valid_ops, capabilities = await _fetch_capabilities()
    cache = get_parse_cache()

    start_ts = time.perf_counter()
    tools = snapshot.get("available_tools", [])
    cached = await cache.get(last_message, tools, model)
    if cached is not None:
        elapsed = time.perf_counter() - start_ts
        logger.info(
            "semantic_planner.cache_hit",
            workflow=True,
            latency_ms=round(elapsed * 1000),
        )
        if isinstance(cached, dict) and "nodes" in cached:
            return _build_patch(cached, cached=True, latency_ms=round(elapsed * 1000))
        if isinstance(cached, list):
            cached = {"version": "1.0", "nodes": cached, "collections": {}}
            return _build_patch(cached, cached=True, latency_ms=round(elapsed * 1000))

    from nexus.agent.prompts.manager import prompt_manager as _pm
    settings = get_settings().agent
    history_str = _format_history(messages)
    try:
        prompt = _pm.render(
            "logical_planner", "2.2",
            capabilities=capabilities if capabilities else "(none available)",
            history=history_str if history_str else "(no prior conversation)",
        )
    except Exception:
        prompt = f"Translate the user request into a workflow with these capabilities: {capabilities}\n\nConversation history:\n{history_str}"

    total_cost: float = 0.0
    total_tokens: int = 0
    parsed: dict[str, Any] | None = None

    # Try instructor first with strict Literal enforcement
    parsed = await _instructor_extract(prompt, last_message, llm, model, settings, valid_ops)

    # Fallback: manual JSON extraction
    if parsed is None:
        logger.info("semantic_planner.fallback_json_extract")
        parsed = await _json_extract(prompt, last_message, llm, model, settings)

    if parsed is None:
        return _build_error_patch(
            Exception("All extraction methods failed"),
            total_tokens,
            total_cost,
        )

    nodes = parsed.get("nodes", [])
    if not isinstance(nodes, list):
        nodes = []
    parsed["nodes"] = nodes[:_SP_MAX_NODES]

    elapsed = time.perf_counter() - start_ts

    await cache.set(last_message, tools, model, parsed)

    # Emit PlanningCompleted event with confidence derived from node count
    session_id = snapshot.get("session_id", "")
    plan_confidence = min(0.95, 0.5 + (len(nodes) * 0.1)) if nodes else 0.0
    await emit_planning_completed(
        session_id=session_id,
        workflow=parsed,
        planner_confidence=plan_confidence,
    )

    logger.info(
        "semantic_planner.complete",
        node_count=len(nodes),
        ops=[n.get("op") for n in nodes if isinstance(n, dict)],
        cached=False,
        latency_ms=round(elapsed * 1000),
    )

    return _build_patch(
        parsed,
        total_tokens=total_tokens,
        cost_usd=total_cost,
        latency_ms=round(elapsed * 1000),
    )


def _build_patch(
    workflow: dict,
    cached: bool = False,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
    latency_ms: int = 0,
) -> StatePatch:
    """Build a StatePatch with the LogicalWorkflow and metadata."""
    updates: dict[str, Any] = {
        "_logical_workflow": workflow,
        "_extraction_result": {
            "node_count": len(workflow.get("nodes", [])),
            "cached": cached,
        },
    }

    if total_tokens:
        updates["_total_tokens"] = total_tokens
        updates["_cost_breakdown"] = {"semantic_planner": cost_usd}
        updates["total_cost_usd"] = cost_usd

    return StatePatch(version=1, updates=updates, ir_stack_update=None)


def _build_error_patch(
    exc: Exception,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
) -> StatePatch:
    """Build error StatePatch when LLM call fails."""
    patch = _build_patch(
        {"version": "1.0", "nodes": [], "collections": {}},
        total_tokens=total_tokens,
        cost_usd=cost_usd,
    )
    patch.updates["errors"] = [f"SemanticPlanner: LLM call failed — {exc}"]
    return patch
