"""WorkflowTemplateEngine — matches user intent to reusable capability chains.

Replaces the old GoalTemplate expansion with a dynamic, DB-backed engine.
Templates are matched by keyword/intent pattern and sorted by priority.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from sqlalchemy import select

from nexus.config.settings import get_settings
from nexus.db.base import async_session as _async_session
from nexus.db.models.workflow_definition import WorkflowDefinition
from nexus.db.models.workflow_template import WorkflowTemplate
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.capabilities.template_engine")

# Reserved metadata keys that should not appear in rendered outputs
_RESERVED_KEYS = frozenset({
    "step", "dependency_type", "metadata",
})


async def match_template(intent_text: str) -> list[dict[str, Any]] | None:
    """Find the best matching workflow (definition or template) for an intent.

    Args:
        intent_text: The user query or intent label (e.g. ``"reconciliation"``).

    Returns:
        The steps (list of dicts) from the highest-priority matching
        workflow, or ``None`` if no match.
    """
    matches = await match_templates(intent_text, limit=1)
    return matches[0] if matches else None


async def match_templates(
    intent_text: str,
    limit: int = 3,
) -> list[list[dict[str, Any]]]:
    """Find all matching workflows (definitions + templates) for an intent.

    Compatibility wrapper around :func:`match_template_candidates` returning
    the step lists of the top-``limit`` matches.

    Returns:
        List of step lists (each a list of step dicts).
    """
    candidates = await match_template_candidates(intent_text, limit=limit)
    return [c["steps"] for c in candidates]


async def match_template_candidates(
    intent_text: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Scored workflow candidates for an intent (single matching implementation).

    Consults BOTH developer-registered ``WorkflowDefinition`` rows (via the
    /workflows API) and seeded ``WorkflowTemplate`` rows, in priority order.
    Returns typed-shaped candidate dicts: ``{id, name, steps, score,
    match_type, tags}`` — used by the ResolutionEngine's workflow stream.

    Args:
        intent_text: The user query or intent label.
        limit: Maximum number of matching workflows to return.

    Returns:
        Ranked candidate dicts (exact match = 100.0; fuzzy = RapidFuzz
        ``token_set_ratio`` score; below threshold excluded).
    """
    q = intent_text.lower().strip()
    if not q:
        return []

    candidates: list[dict[str, Any]] = []
    try:
        # Hybrid matching (Phase 6): a cached query embedding enables
        # vector-cosine + fuzzy + metadata scoring when candidate embeddings
        # exist; missing embeddings degrade gracefully to fuzzy-only.
        query_embedding = await _embed_query(q)
        async with _async_session() as session:
            defs = (
                await session.execute(
                    select(WorkflowDefinition)
                    .where(WorkflowDefinition.enabled == True)  # noqa: E712
                    .order_by(WorkflowDefinition.priority.desc())
                )
            ).scalars().all()
            for wf in defs:
                pattern = wf.trigger_intent_pattern.lower().strip()
                if not pattern:
                    continue
                if pattern in q:
                    score, match_type = 100.0, "exact"
                else:
                    score, match_type = _fuzzy_score(q, pattern)
                    if score is None:
                        continue
                    if query_embedding is not None and getattr(wf, "embedding", None):
                        cosine = _cosine_similarity(query_embedding, wf.embedding)
                        # Hybrid: 0.5 vector + 0.5 fuzzy + small metadata boost
                        # (registered priority, capped).
                        metadata_boost = min(3.0, float(wf.priority or 0) * 0.3)
                        score = round(0.5 * (cosine * 100.0) + 0.5 * score + metadata_boost, 3)
                        match_type = "hybrid"
                steps = wf.steps
                if steps and isinstance(steps, list):
                    logger.info(
                        "template_engine.matched_definition",
                        workflow=wf.name,
                        pattern=pattern,
                        steps=len(steps),
                        match_type=match_type,
                    )
                    candidates.append({
                        "id": str(wf.id),
                        "name": wf.name,
                        "steps": steps,
                        "score": score,
                        "match_type": match_type,
                        "tags": [],
                    })
                    if len(candidates) >= limit:
                        return candidates

            if len(candidates) < limit:
                result = await session.execute(
                    select(WorkflowTemplate)
                    .where(WorkflowTemplate.enabled == True)  # noqa: E712
                    .order_by(WorkflowTemplate.priority.desc())
                )
                for tmpl in result.scalars().all():
                    pattern = tmpl.trigger_intent_pattern.lower().strip()
                    if not pattern:
                        continue
                    if pattern in q:
                        score, match_type = 100.0, "exact"
                    else:
                        score, match_type = _fuzzy_score(q, pattern)
                        if score is None:
                            continue
                    chain = tmpl.capability_chain
                    if chain and isinstance(chain, list):
                        logger.info(
                            "template_engine.matched",
                            template=tmpl.name,
                            pattern=pattern,
                            steps=len(chain),
                        )
                        candidates.append({
                            "id": str(tmpl.id),
                            "name": tmpl.name,
                            "steps": chain,
                            "score": score,
                            "match_type": match_type,
                            "tags": [str(tag) for tag in (tmpl.tags or [])],
                        })
                        if len(candidates) >= limit:
                            break
    except Exception as exc:
        logger.warning("template_engine.db_error", error=str(exc))

    return candidates


def _fuzzy_score(query: str, pattern: str) -> tuple[float, str] | tuple[None, str]:
    """RapidFuzz token_set score for a pattern; None when below threshold."""
    if not pattern or not query:
        return None, "fuzzy"
    try:
        from rapidfuzz import fuzz

        from nexus.config.settings import get_settings as _tpl_settings

        threshold = 95.0
        try:
            threshold = float(_tpl_settings().resolver.fuzzy_threshold)
        except Exception:
            threshold = 95.0
        score = float(fuzz.token_set_ratio(query.lower(), pattern.lower()))
        return (score, "fuzzy") if score >= threshold else (None, "fuzzy")
    except Exception:
        return None, "fuzzy"


async def _embed_query(query: str) -> list[float] | None:
    """Best-effort, cached query embedding for hybrid matching.

    Returns None when embeddings are unavailable — callers fall back to
    fuzzy-only (never breaks matching).
    """
    import hashlib

    try:
        import json as _json

        from nexus.redis_client.client import get_redis_client

        text_hash = hashlib.sha256(query.encode()).hexdigest()
        cache_key = f"tpl_embed:{text_hash}"
        redis = get_redis_client()
        if redis is not None:
            cached = await redis.get(cache_key)
            if cached:
                return _json.loads(cached)
        from nexus.config.settings import get_settings as _embed_settings
        from nexus.llm.client import LLMClient

        model = _embed_settings().llm.embedding_model
        embeddings = await LLMClient().embed(model, [query])
        if embeddings and embeddings[0]:
            result = embeddings[0]
            if redis is not None:
                await redis.setex(cache_key, 3600, _json.dumps(result))
            return result
    except Exception:
        pass
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embedding vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return max(0.0, min(1.0, dot / (na * nb)))



async def expand_template_chain(
    chain: list[dict[str, Any]],
    max_depth: int = 4,
    _current_depth: int = 0,
) -> list[dict[str, Any]]:
    """Recursively expand a capability chain, resolving nested template references.

    Each step in the chain can be:
    - ``{"capability": "some_tool", "inputs": {...}}`` — a concrete capability
    - ``{"template": "template_name", "inputs": {...}}`` — a reference to another
      WorkflowTemplate, which will be expanded inline

    Args:
        chain: The capability chain to expand.
        max_depth: Max recursion depth for template nesting.
        _current_depth: Internal recursion tracker.

    Returns:
        Expanded capability list with all template references resolved.
    """
    if _current_depth >= max_depth:
        logger.warning("template_engine.max_depth", depth=max_depth)
        return chain

    expanded: list[dict[str, Any]] = []
    for step in chain:
        if not isinstance(step, dict):
            expanded.append(step)
            continue

        # Filter out internal/reserved keys from step output
        clean_step = {k: v for k, v in step.items() if k not in _RESERVED_KEYS}

        template_ref = step.get("template")
        if template_ref:
            # Load the referenced template's chain and recurse
            sub_chain = await match_template(template_ref)
            if sub_chain:
                sub_expanded = await expand_template_chain(
                    sub_chain,
                    max_depth=max_depth,
                    _current_depth=_current_depth + 1,
                )
                expanded.extend(sub_expanded)
            else:
                # Template not found — use as regular capability
                clean_step["capability"] = template_ref
                expanded.append(clean_step)
            continue

        # Workflow-as-building-block: a step that references another
        # deterministic workflow definition is expanded inline, keeping the
        # referenced workflow's step ids intact so ${step_X} wiring survives.
        workflow_ref = step.get("workflow_ref")
        if workflow_ref:
            sub_chain = await match_template(workflow_ref)
            if sub_chain:
                sub_expanded = await expand_template_chain(
                    sub_chain,
                    max_depth=max_depth,
                    _current_depth=_current_depth + 1,
                )
                expanded.extend(sub_expanded)
            else:
                # Referenced workflow missing — keep as a capability-shaped
                # step so the planner can still attempt dynamic resolution.
                clean_step["intent"] = workflow_ref
                expanded.append(clean_step)
            continue

        # Keep ANY executable step: keyed by ``capability`` (legacy),
        # ``intent`` (current seed format), or ``dynamic`` (hybrid step
        # whose capability is planned at runtime). Dropping intent-keyed
        # steps silently emptied template chains and triggered a garbage
        # LLM fallback — this was the root cause of the broken hybrid run.
        if (
            "capability" in step
            or "intent" in step
            or step.get("dynamic") is True
            or step.get("dynamic") == "true"
        ):
            expanded.append(clean_step)

    return expanded


class WorkflowTemplateEngine:
    """Dynamically composes workflows from templates or LLM generation."""

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or LLMClient()

    async def compose_workflow(
        self,
        intent: str,
        available_capabilities: list[str],
        user_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Find or generate a workflow definition dynamically.

        Args:
            intent: The user's intent string.
            available_capabilities: List of capability names available in the system.
            user_context: Additional user context for workflow generation.

        Returns:
            A workflow definition dict with a ``steps`` list.
        """
        # 1. Try DB match first — COMPOSE all matching templates into one
        # workflow (workflow-as-building-block): a single request may match
        # several deterministic workflows; their chains are concatenated.
        # Step ids are preserved when unique; on collision (two chains both
        # using step_1), the later step is renumbered AND its ``${old}``
        # input references are remapped so variable wiring stays consistent.
        db_templates = await match_templates(intent)
        if db_templates:
            combined: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for chain in db_templates:
                expanded = await expand_template_chain(chain)
                for step in expanded:
                    if not isinstance(step, dict):
                        continue
                    step = dict(step)
                    step_id = str(step.get("id") or f"step_{len(combined) + 1}")
                    if step_id in seen_ids:
                        old_id = step_id
                        step_id = f"step_{len(combined) + 1}"
                        step["id"] = step_id
                        # Remap references in THIS step's own inputs
                        inputs = step.get("inputs") or {}
                        step["inputs"] = {
                            k: str(v).replace(f"${{{old_id}", f"${{{step_id}")
                            for k, v in inputs.items()
                        }
                        # Remap references in ALL previously combined steps
                        for prev in combined:
                            prev_inputs = prev.get("inputs") or {}
                            prev["inputs"] = {
                                k: str(v).replace(f"${{{old_id}", f"${{{step_id}")
                                for k, v in prev_inputs.items()
                            }
                    else:
                        step.setdefault("id", step_id)
                    seen_ids.add(step_id)
                    combined.append(step)
            if combined:
                return {
                    "name": "db_template",
                    "steps": combined,
                }

        # 2. LLM-assisted generation
        return await self._generate_workflow_llm(intent, available_capabilities, user_context)

    async def _generate_workflow_llm(
        self,
        intent: str,
        capabilities: list[str],
        user_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Use LLM to generate a workflow definition dynamically."""
        # Prefer LOGICAL op names (e.g. ``get_weather``) over category slugs
        # (e.g. ``weather_get_weather``) so the LLM picks real capabilities.
        # Dynamic, structural: any name that contains another name as a
        # suffix is treated as a slug and de-prioritised.
        def _is_slug(name: str) -> bool:
            lowered = name.lower()
            for other in capabilities:
                other_l = other.lower()
                if other_l != lowered and lowered.endswith("_" + other_l):
                    return True
            return False

        preferred = [c for c in capabilities if not _is_slug(c)][:20]
        caps_str = "\n".join([f"- {c}" for c in preferred]) or \
            "\n".join([f"- {c}" for c in capabilities[:20]])

        system_prompt = (
            "You are an expert workflow orchestrator AI. Your task is to design a multi-step "
            "workflow to fulfill a user's request based on available capabilities.\n"
            "You must respond with ONLY a valid JSON object. No markdown, no explanations.\n"
            "The JSON must follow this exact schema:\n"
            "{\n"
            '  "name": "string",\n'
            "  \"steps\": [\n"
            "    {\n"
            '      "id": "step_1",\n'
            '      "description": "string",\n'
            '      "intent": "capability_name | <empty when dynamic>",\n'
            '      "requires_input": boolean,\n'
            '      "question": "string (if requires_input is true)",\n'
            '      "dynamic": false,\n'
            '      "inputs": {"key": "value or ${variable_name}"}\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Set \"dynamic\": true ONLY when the step's capability is not known "
            "in advance and must be planned at runtime from the user's needs "
            "(its intent/description becomes the planning prompt)."
        )

        user_prompt = (
            f"User Intent: {intent}\n\n"
            f"Available Capabilities:\n{caps_str}\n\n"
            "Rules:\n"
            "1. Only use capabilities from the provided list.\n"
            "2. If a step needs user input (like choosing a database), set requires_input=true and provide a clear question.\n"
            "3. Use the exact capability name as the 'intent'.\n"
            "4. To pass data from a previous step, use the step's 'id' as the variable name, e.g., \"${step_1}\".\n"
            "5. The final step should produce the requested artifact.\n\n"
            "Example Output (names are structural placeholders — use the "
            "EXACT capability names from the provided list):\n"
            "{\n"
            '  "name": "my_workflow",\n'
            "  \"steps\": [\n"
            '    {"id": "step_1", "description": "First capability", "intent": "<capability_name_A>", "requires_input": true, "question": "What would you like to use?", "inputs": {}},\n'
            '    {"id": "step_2", "description": "Second capability", "intent": "<capability_name_B>", "requires_input": false, "inputs": {"value": "${step_1}"}}\n'
            "  ]\n"
            "}"
        )

        try:
            response = await self.llm.complete(
                model=get_settings().llm.default_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=1024,
            )

            if response.failed:
                logger.warning("workflow_generation_llm_failed", error=response.error)
                return None

            content = response.content or ""
            logger.debug("workflow_generation_llm_response", content=content)

            json_str = self._extract_json(content)
            if json_str:
                json_str = re.sub(r",\s*([}\]])", r"\1", json_str)

                workflow_def = json.loads(json_str)
                if "steps" in workflow_def and isinstance(workflow_def["steps"], list):
                    for step in workflow_def["steps"]:
                        if "id" not in step or "intent" not in step:
                            logger.warning("workflow_generation_invalid_step", step=step)
                            return None
                    return workflow_def
                else:
                    logger.warning("workflow_generation_missing_steps", response=content)
            else:
                logger.warning("workflow_generation_no_json_found", response=content)

        except json.JSONDecodeError as e:
            logger.error("workflow_generation_json_decode_failed", error=str(e), content=content)
        except Exception as exc:
            logger.error("workflow_generation_llm_failed", error=str(exc))

        return None

    @staticmethod
    def _extract_json(text: str) -> str | None:
        """Extract JSON string from text, handling markdown code fences and tags."""
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()

        match = re.search(r"<json>\s*([\s\S]*?)\s*</json>", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1].strip()

        return None
