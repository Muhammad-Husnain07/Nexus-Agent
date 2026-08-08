"""ResponseNode — Lowering Pass: typed Artifacts to natural language.

This is the final lowering pass in the compiler pipeline.  It reads
typed Artifacts from the ArtifactGraph and the user's original query
from the message history, and produces a natural-language response.

Critically, it does NOT reference raw result dicts (those paths are
deprecated).  All structured data arrives as ArtifactBase instances
registered in the ArtifactGraph.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.artifacts.graph import get_artifact_graph
from nexus.compiler.context_ir import (
    ContextIR,
    ContextItem,
    ContextSection,
    Priority,
    PromptProjection,
)
from nexus.compiler.prompt_cache import PromptCache
from nexus.compiler.prompt_pipeline import CompilerPipeline
from nexus.compiler.prompt_renderer import ModelProfile, PromptRenderer
from nexus.compiler.prompt_strategies import PROGRESSIVE_STRATEGIES
from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient

_PROMPT_CACHE = PromptCache(local_memory_mb=50)

logger = structlog.get_logger("nexus.agent.nodes.response")

# A degenerate response is one that carries no real content. Detection is
# purely STRUCTURAL (no hardcoded word/phrase lists anywhere): a response
# shorter than this threshold cannot meaningfully answer anything (every
# previously-observed generic fallback — "I processed your request.",
# "Task completed.", "Done." — is far below it).
_DEGENERATE_MIN_LENGTH: int = 40

_DEGENERATE_RETRIES: int = 2


def _render_artifacts(artifact_list: list[Any]) -> str:
    """Deterministic fallback: render registered artifacts into readable text.

    Used when LLM synthesis fails or stays degenerate — successful tool
    outputs must NEVER be discarded because one formatter failed. Renders
    every artifact through the pluggable RendererRegistry (metadata-driven
    renderer plugins; GenericRenderer is the default). Null values are
    skipped (never rendered as "None"). Falls back to a compact JSON
    preview when even the renderers fail.
    """
    try:
        from nexus.artifacts.renderers.registry import RendererRegistry

        RendererRegistry.initialize()
    except Exception:
        RendererRegistry = None  # type: ignore[assignment]

    sections: list[str] = []
    for art in artifact_list:
        data = getattr(art, "data", None) or {}
        tool = getattr(art, "tool_name", "") or getattr(art, "capability_id", "") or "tool"
        if RendererRegistry is not None:
            try:
                renderer = RendererRegistry.get(tool)
                text = renderer.render(data) if renderer else ""
            except Exception:
                text = ""
        else:
            text = ""
        if not text:
            try:
                compact = json.dumps(data, ensure_ascii=False, default=str)
                text = compact[:2000] + ("..." if len(compact) > 2000 else "")
            except Exception:
                text = ""
        if text:
            sections.append(f"{tool}:\n{text}")

    if not sections:
        return ""
    return "\n\n".join(sections)


def _is_degenerate(text: str) -> bool:
    """Return True if the response is degenerate (too short to carry content).

    Structural only — no hardcoded phrase lists: a response below
    ``_DEGENERATE_MIN_LENGTH`` characters cannot meaningfully answer the
    user (the system's generic fallback texts are all far shorter).
    """
    stripped = text.strip()
    if len(stripped) < _DEGENERATE_MIN_LENGTH:
        return True
    return False


def _synthesis_incorporates_data(text: str, artifact_list: list[Any]) -> bool:
    """True when the synthesized text actually engages the artifact data.

    The fast synthesis model occasionally claims "no data" while real
    artifacts exist (every-domain failure class). This cross-check is
    derived from the artifact payloads THEMSELVES (no hardcoding): if the
    response incorporates at least one non-trivial scalar value from the
    registered artifacts, the synthesis engaged the data — otherwise the
    deterministic Artifact Renderer takes over (data must never be
    discarded by a formatter/synthesis failure).
    """
    if not artifact_list:
        return True
    return _covered_artifacts(text, artifact_list) > 0


def _synthesis_covers_each_artifact(text: str, artifact_list: list[Any]) -> bool:
    """Response coverage (P0): EVERY registered artifact must be represented
    in the response by at least one of its values — the "3 intents, 3
    tools, 2 answers" hole. When any artifact is uncited, the deterministic
    renderer (which renders every artifact) guarantees the coverage."""
    if not artifact_list:
        return True
    return _covered_artifacts(text, artifact_list) == len(artifact_list)


def _covered_artifacts(text: str, artifact_list: list[Any]) -> int:
    """Count of artifacts with at least one non-trivial scalar value cited
    in the text (frozen-payload aware — MappingProxyType descent)."""
    from types import MappingProxyType

    def _values_of(data: Any) -> list[str]:
        meaningful: list[str] = []

        def _collect(value: Any) -> None:
            if isinstance(value, MappingProxyType):
                _collect(dict(value))
            elif isinstance(value, dict):
                for v in value.values():
                    _collect(v)
            elif isinstance(value, (list, tuple)):
                for v in value:
                    _collect(v)
            elif value is not None and not isinstance(value, (bool, dict, list, tuple)):
                s = str(value).strip()
                if len(s) >= 3 and s.lower() != "none":
                    meaningful.append(s)

        _collect(data)
        return meaningful

    covered = 0
    for art in artifact_list:
        values = _values_of(getattr(art, "data", None))
        if any(v in text for v in values):
            covered += 1
    return covered


def _synthesis_fallback_patch(
    state: AgentState,
    artifact_list: list[Any],
    note: str,
) -> dict[str, Any]:
    """Synthesis-recovery patch: artifacts exist → render them deterministically.

    Execution succeeded and artifacts are present, so the user-facing answer
    MUST be data-backed — never an error. The LLM is the primary synthesizer;
    when it fails or stays degenerate, the pluggable Artifact Renderer
    produces the answer. ``_synthesis_failed`` records the degraded path
    (observability) and is NOT an execution error — ``_executor_all_success``
    stays true and ``response_type`` is never ``error``.
    """
    text = _render_artifacts(artifact_list)
    if not text:
        logger.error("response_node.renderer_empty", note=note[:80])
        return {
            "final_response": note,
            "_routing_decision": "finalize",
            "_synthesis_failed": True,
        }
    final = (
        "I retrieved the following results:\n\n" + text
        if len(text) > 20
        else note
    )
    logger.info("response_node.synthesis_fallback", response_type="artifact")
    return {
        "final_response": final,
        "_routing_decision": "finalize",
        "response_type": "artifact",
        "_synthesis_failed": True,
    }


async def response_node(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Compose the final response from ArtifactGraph + conversation history.

    Lowering Pass: transforms typed Artifacts back into natural language
    based on the user's original query.  Falls back to conversation mode
    when no artifacts exist (pure chat).
    """
    existing = state.get("final_response")
    if existing and (
        state.get("response_type")
        in ("greeting", "meta", "clarification", "knowledge", "cancellation", "background")
        or state.get("_needs_approval")
    ):
        return {"final_response": existing, "_routing_decision": "finalize"}

    artifacts = get_artifact_graph(str(state.get("session_id", "")))
    artifact_list = artifacts.all()

    # Structured Artifact Passthrough — workflow artifacts render
    # deterministically (never the generic "Artifact generated successfully.")
    structured_payload = state.get("_structured_payload")
    if structured_payload and state.get("response_type") == "artifact":
        logger.info("response_node.structured_passthrough")
        rendered = _render_artifacts(artifact_list) if artifact_list else ""
        final = rendered or existing or "Artifact generated successfully."
        return {
            "final_response": final,
            "_structured_payload": structured_payload,
            "_routing_decision": "finalize",
            "response_type": "artifact",
        }

    errors = state.get("errors", [])

    # Pure conversation — no artifacts, no tools
    workflow = state.get("_logical_workflow", {})
    nodes = workflow.get("nodes", []) if isinstance(workflow, dict) else []
    if not artifact_list and not errors and len(nodes) == 0:
        messages = state.get("messages", [])
        chat_messages = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages if isinstance(m, dict)
        ]
        try:
            response = await llm.complete(
                model=model, messages=chat_messages,
                temperature=0.7, max_tokens=500,
            )
            final = (response.content or "").strip()
            # Empty conversational output is a synthesis failure, not an
            # answer — retry ONCE (the fast model occasionally returns
            # nothing); only then fall back to the honest generic text.
            if not final and not response.failed:
                logger.warning("response_node.native_chat_empty_retry")
                response = await llm.complete(
                    model=model, messages=chat_messages,
                    temperature=0.8, max_tokens=500,
                )
                final = (response.content or "").strip()
            if not final:
                logger.warning("response_node.native_chat_empty")
                final = "I processed your request."
            return {
                "final_response": final,
                "_routing_decision": "finalize",
                "response_type": "conversational",
            }
        except Exception as exc:
            logger.error("response_node.native_chat_failed", error=str(exc))
            return {"final_response": "I'm not sure how to respond.", "_routing_decision": "finalize", "response_type": "error"}

    if not artifact_list and not errors:
        return {"final_response": "I processed your request.", "_routing_decision": "finalize", "response_type": "tool"}

    if errors and not artifact_list:
        logger.error("response_node.execution_errors", errors=errors)
        reason = "; ".join(str(e) for e in errors[:3])
        final = (
            "I couldn't complete that request: " + reason
            if reason
            else "I'm sorry, I encountered issues executing the tools."
        )
        return {
            "final_response": final,
            "_routing_decision": "finalize",
            "response_type": "error",
        }

    # ExecutionBudget degradation (Phase 3): planning over budget → the
    # deterministic Artifact Renderer answers immediately (no slow LLM
    # synthesis) — the system stays responsive under load.
    if state.get("_budget_exceeded") == "planning" and artifact_list:
        logger.info("response_node.budget_renderer", budget=state.get("_budget_exceeded"))
        return _synthesis_fallback_patch(
            state, artifact_list,
            "I'm sorry, I encountered an issue while composing the response. Please try again.",
        )

    # Compile ContextIR and run prompt pipeline (no fallback — fail fast on errors)
    try:
        _compiled_ir, compiled_messages = await _compile_and_render(
            state=state,
            artifact_list=artifact_list,
            model=model,
        )
    except Exception as exc:
        logger.error("response_node.compilation_failed", error=str(exc))
        return {"final_response": "I'm sorry, I encountered an issue processing the context.", "_routing_decision": "finalize"}

    _fin_settings = get_settings().agent

    # REASONING BUDGET (P0): the synthesis LLM call consumes the shared
    # llm-call budget; the ledger flows back on every return below.
    _llm_budget = {}
    try:
        from nexus.agent.budget import budget_from_state

        _bud = budget_from_state(state)
        _bud.consume("llm_calls")
        _llm_budget = _bud.to_dict()
    except Exception:
        _llm_budget = {}

    # Guard LLM call with timeout fallback — prevents hanging when model is unreachable
    try:
        if compiled_messages:
            # Use pipeline-compiled messages
            response = await asyncio.wait_for(
                llm.complete(
                    model=model,
                    messages=compiled_messages,
                    temperature=_fin_settings.finalize_temperature,
                    max_tokens=_fin_settings.finalize_max_tokens,
                ),
                timeout=max(90, _fin_settings.finalize_max_tokens // 30),
            )
            if response.failed:
                logger.error("response_node.llm_failed", error=response.error)
                if artifact_list:
                    return _synthesis_fallback_patch(
                        state, artifact_list,
                        "I'm sorry, I encountered an issue while composing the response. Please try again.",
                    )
                return {
                    "final_response": "I'm sorry, I encountered an issue while composing the response. Please try again.",
                    "_routing_decision": "finalize",
                    "errors": state.get("errors", []) + [f"LLM call failed: {response.error}"],
                }
            final = response.content or "Task completed."
            # DATA INCORPORATION + RESPONSE-COVERAGE GUARD: a synthesized
            # answer that engages NONE of the registered artifact values —
            # or fails to cite EVERY artifact (the "3 intents, 2 answers"
            # hole) — must not stand: the deterministic Artifact Renderer
            # produces the data-backed, coverage-complete answer instead.
            if artifact_list and (
                not _synthesis_incorporates_data(final, artifact_list)
                or not _synthesis_covers_each_artifact(final, artifact_list)
            ):
                logger.warning(
                    "response_node.synthesis_ignored_artifacts",
                    text_len=len(final or ""),
                )
                return _synthesis_fallback_patch(
                    state, artifact_list,
                    "I retrieved the following results:",
                )
        else:
            # Fallback (should not happen — compiled_messages is always set from pipeline)
            msgs = compiled_messages or [{"role": "user", "content": _last_user_message(state) or ""}]
            response = await asyncio.wait_for(
                llm.complete(
                    model=model,
                    messages=msgs,
                    temperature=_fin_settings.finalize_temperature,
                    max_tokens=_fin_settings.finalize_max_tokens,
                ),
                timeout=max(90, _fin_settings.finalize_max_tokens // 30),
            )
            if response.failed:
                logger.error("response_node.llm_failed", error=response.error)
                if artifact_list:
                    return _synthesis_fallback_patch(
                        state, artifact_list,
                        "I'm sorry, I encountered an issue while composing the response. Please try again.",
                    )
                return {
                    "final_response": "I'm sorry, I encountered an issue while composing the response. Please try again.",
                    "_routing_decision": "finalize",
                    "errors": state.get("errors", []) + [f"LLM call failed: {response.error}"],
                }
            final = response.content or "Task completed."
    except (asyncio.TimeoutError, Exception) as exc:
        err_msg = str(exc) or type(exc).__name__
        logger.error("response_node.llm_failed", error=err_msg)
        if artifact_list:
            return _synthesis_fallback_patch(
                state, artifact_list,
                "I'm sorry, I encountered an issue while composing the response. Please try again.",
            )
        return {"final_response": "I'm sorry, I encountered an issue while composing the response. Please try again.", "_routing_decision": "finalize"}

    # Degenerate response guard — retry with stricter prompt if needed
    for attempt in range(_DEGENERATE_RETRIES):
        if _is_degenerate(final):
            logger.warning("response_node.degenerate_response", attempt=attempt + 1, text=final[:60])
            # Use pipeline messages (or fallback to raw user message)
            messages = compiled_messages or [{"role": "user", "content": _last_user_message(state)}]
            try:
                response = await asyncio.wait_for(
                    llm.complete(
                        model=model,
                        messages=messages,
                        temperature=_fin_settings.finalize_temperature + 0.1,
                        max_tokens=_fin_settings.finalize_max_tokens,
                    ),
                timeout=max(90, _fin_settings.finalize_max_tokens // 30),
                )
                if response.failed:
                    logger.error("response_node.degenerate_retry_llm_failed", error=response.error)
                    break
                final = response.content or "Task completed."
            except (asyncio.TimeoutError, Exception) as exc:
                logger.error("response_node.degenerate_retry_failed", error=str(exc))
                break
        else:
            break

    # If still degenerate after retries, render artifacts deterministically —
    # successful execution must never surface as a user-facing error.
    if _is_degenerate(final):
        logger.error("response_node.degenerate_after_retries", text=final[:60])
        if artifact_list:
            return _synthesis_fallback_patch(
                state, artifact_list,
                "I'm sorry, I couldn't process the tool results.",
            )
        return {"final_response": "I'm sorry, I couldn't process the tool results.", "_routing_decision": "finalize", "response_type": "error"}

    # Build final message
    _milestone_min = get_settings().agent.milestone_min_length
    _is_clarification = len(final) < _milestone_min
    final_msg = {
        "role": "assistant",
        "content": final,
        "_milestone": not _is_clarification,
    }

    from nexus.agent.nodes.memory_helper_node import persist_after_response
    session_factory = None
    working_memory_update = await persist_after_response(
        state, final, llm=llm, session_factory=session_factory,
    )

    return {
        "messages": [final_msg],
        "final_response": final,
        "working_memory": working_memory_update,
        "_routing_decision": "finalize",
        "_invocation_budget": _llm_budget,
        # RESPONSE COVERAGE (P2 eval): the fraction of artifacts cited in
        # the final response — the "3 intents, 2 answers" detector.
        "_response_coverage": (
            _covered_artifacts(final, artifact_list) / len(artifact_list)
            if artifact_list else 1.0
        ),
    }


def _last_user_message(state: AgentState) -> str:
    messages = state.get("messages", [])
    if isinstance(messages, list):
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                return str(m.get("content", ""))
    return ""


# ============================================================================
# Prompt Pipeline Integration
# ============================================================================


class _SimpleEstimator:
    """Simple token estimator that counts characters/4."""

    @staticmethod
    def estimate_messages(messages: list[dict]) -> int:
        return sum(len(m.get("content", "")) // 4 for m in messages)


async def _compile_and_render(
    state: AgentState,
    artifact_list: list,
    model: str,
) -> tuple[ContextIR, list[dict]]:
    """Build a ContextIR from state and artifacts, run the pipeline, render to messages.

    Returns:
        (compiled_ir, rendered_messages) tuple.

    Raises:
        Exception: If any stage fails, caller falls back to prompt_manager.
    """
    from nexus.artifacts.renderers.registry import RendererRegistry

    RendererRegistry.initialize()  # idempotent — only runs once

    # Build ContextIR items
    items: list[ContextItem] = []

    # 1. System Instructions (V4.0 Artifact-aware Lowering Pass)
    from nexus.agent.prompts.manager import prompt_manager
    try:
        system_prompt = prompt_manager.render("finalize", version="4.0", tool_citations="", errors_summary="")
        system_prompt = system_prompt.replace("**Artifacts:**\n\n", "").replace("**Errors:**\n", "")
    except Exception:
        system_prompt = "You are answering the user's question using the provided facts (Artifacts). Do NOT summarize execution status."
    if system_prompt:
        items.append(ContextItem(
            section=ContextSection.SYSTEM_INSTRUCTIONS,
            speaker="system",
            content=system_prompt,
            priority=Priority.SYSTEM,
        ))

    # 2. User intent
    last_query = _last_user_message(state)
    if last_query:
        items.append(ContextItem(
            section=ContextSection.USER_INTENT,
            speaker="user",
            content=last_query,
            priority=Priority.CURRENT_USER,
        ))

    # Artifacts
    schema_versions: dict[str, str] = {}
    for a in artifact_list:
        cap_id = getattr(a, "capability_id", "") or a.tool_name
        schema_versions[cap_id] = getattr(a, "schema_version", "1.0")
        projection = PromptProjection.from_artifact(a)
        items.append(ContextItem(
            section=ContextSection.ARTIFACTS,
            speaker="assistant",
            projection=projection,
            priority=Priority.ARTIFACT,
        ))

    # History (limited to last 10 messages)
    messages = state.get("messages", [])
    if isinstance(messages, list):
        for m in messages[-10:]:
            role = m.get("role", "") if isinstance(m, dict) else ""
            content = m.get("content", "") if isinstance(m, dict) else ""
            if role and content and content != last_query:
                items.append(ContextItem(
                    section=ContextSection.HISTORY,
                    speaker=role,
                    content=content,
                    priority=Priority.RECENT_HISTORY,
                ))

    # Build IR
    from nexus.compiler.context_ir import ContextPolicy

    ir = ContextIR(
        items=tuple(items),
        schema_versions=schema_versions,
        budget_limit=120000,  # Leave 8K room for model output
        model_name=model,
        policy=ContextPolicy(purpose="finalize", max_history_turns=5, max_artifacts=8),
    )

    # Run pipeline
    pipeline = CompilerPipeline(prompt_cache=_PROMPT_CACHE)
    renderer = PromptRenderer()
    estimator = _SimpleEstimator()

    pipeline_result = await pipeline.run(
        ir=ir,
        policy=ir.policy,
        estimator=estimator,
        renderer=renderer,
        use_cache=True,
    )

    current_ir = pipeline_result.ir

    # Render with progressive fallback
    max_attempts = len(PROGRESSIVE_STRATEGIES)
    attempt = 0
    compiled_messages, report = await renderer.render(current_ir, ModelProfile(True), model)

    while not report.is_valid and attempt < max_attempts:
        attempt += 1
        strategy = PROGRESSIVE_STRATEGIES[attempt - 1]
        logger.warning("response_node.budget_overflow", attempt=attempt, strategy=strategy.__class__.__name__, overflow=report.overflow)
        current_ir, _ = strategy.apply(current_ir, {})
        compiled_messages, report = await renderer.render(current_ir, ModelProfile(True), model)

    if not report.is_valid:
        raise ValueError(f"Prompt exceeds budget by {report.overflow} tokens after all strategies")

    # Cache the result
    try:
        from nexus.artifacts.renderers.registry import RendererRegistry
        _cache_fp = current_ir.fingerprint(RendererRegistry.version_hash())
        _PROMPT_CACHE.set(_cache_fp, model, ir.budget_limit, compiled_messages)
    except Exception:
        pass  # cache failure is non-fatal

    return current_ir, compiled_messages
