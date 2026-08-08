"""Query classifier — two-stage query-type detection.

Two-stage classification:
1. **Heuristic** (~0ms): greeting keywords, single tool name, conjunctions,
   follow-up detection from conversation history.
2. **LLM** (~500ms): compact few-shot call for ambiguous/multi-tool queries
   to distinguish INDEPENDENT_MULTI from DEPENDENT_MULTI.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any

import structlog

from nexus.agent.state import AgentState
from nexus.config.settings import get_settings
from nexus.agent.goals import ExecutionGoal, ExecutionGoals
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.router")


# ============================================================================
# Query Type Enum
# ============================================================================

class QueryType(str, Enum):
    """Legacy query-type classification.

    DEPRECATED (roadmap Phase 2): routing now uses ``ExecutionGoals``
    (composable flags). This enum is retained for backward compatibility with
    persisted checkpoints via ``ExecutionGoals.from_legacy``.
    """

    SINGLE_TOOL = "single_tool"
    INDEPENDENT_MULTI = "independent_multi"
    DEPENDENT_MULTI = "dependent_multi"
    CONVERSATIONAL = "conversational"
    NO_TOOL_NEEDED = "no_tool"
    KNOWLEDGE_ONLY = "knowledge_only"
    NEEDS_REQUIREMENTS = "needs_requirements"
    WORKFLOW = "workflow"


# ============================================================================
# Few-Shot System Prompt (managed by PromptManager)
# ============================================================================

_CLASSIFIER_PROMPT: str = ""
try:
    from nexus.agent.prompts.manager import prompt_manager
    _CLASSIFIER_PROMPT = prompt_manager.render("router", version="1.3")
except Exception:
    _CLASSIFIER_PROMPT = (
        "You are a query goal classifier. Return JSON with: "
        "\"goals\": a non-empty list of 'conversation' | 'information' | "
        "'analysis' | 'action' | 'workflow', and \"needs_requirements\": "
        "true when the request lacks essential details. "
        "Rules: greetings/meta = conversation; explain/teach/research = "
        "information; multi-step reasoning without side effects = analysis; "
        "anything calling a tool or changing state = action; business "
        "processes with fixed steps = workflow; 'analyze sales and email "
        "the report' = ['analysis', 'action']."
    )


# ============================================================================
# Heuristic Classification (Stage 1 — fast path)
# ============================================================================

# Capability-based keyword matching — uses GlobalContext O(1) map
# (keyword → capabilities built from the DB registry at startup — data-driven,
# NOT hardcoded phrase lists). Language classification (greetings, knowledge,
# conversational, multi-intent) is delegated to the LLM classifier.


def _tokenize_query(text: str) -> list[str]:
    """Tokenize a user query: lowercase, strip punctuation, split."""
    import re
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return [t for t in text.split() if len(t) > 1]


# ============================================================================
# Capability-based keyword matching (replaces old tool-based _match_tools)
# ============================================================================
# Capability-based keyword matching (replaces old tool-based _match_tools)
# ============================================================================


def _reset_keyword_index() -> None:
    """No-op — keyword matching now uses GlobalContext.  Kept for backward compat."""
    pass


def _get_capability_keywords() -> dict[str, list[str]]:
    """Return the O(1) capability_keywords map from GlobalContext."""
    try:
        from nexus.context.global_context import get_global_context
        gc = get_global_context()
        return gc.capability_keywords or {}
    except Exception:
        return {}


def _match_capabilities(query: str) -> set[str]:
    """Tokenize the user query and match capabilities via GlobalContext O(1) keyword map.

    Returns a set of matched capability names.  Replaces the old ``_match_tools()``
    that scanned ``available_tools`` in state.

    No hardcoded word lists: a keyword-map token that maps to MANY
    capabilities is GENERIC (a prose word like ``with`` inherited from graph
    seeds maps to several caps and is no signal) — computed from the map's
    own frequency distribution, exactly like the retrieval engine's
    genericity rule.
    """
    tokens = _tokenize_query(query)
    if not tokens:
        return set()
    kw_map = _get_capability_keywords()
    generic = {
        key for key, caps in kw_map.items()
        if len(caps) > 3
    }
    scores: dict[str, float] = {}
    for token in tokens:
        if token in generic:
            continue
        for cap_name in kw_map.get(token, []):
            scores[cap_name] = scores.get(cap_name, 0) + 1.0
        # Exact capability name match (weight 5.0)
        for cap_name in kw_map.get(token, []):
            if cap_name.replace("_", " ").lower() == token:
                scores[cap_name] = scores.get(cap_name, 0) + 5.0
    return {c for c, s in scores.items() if s >= 1.0}


def _domain_hint(query: str) -> str | None:
    """Best-effort domain hint from the query (capability classification).

    Deterministic, metadata-driven: for every domain in the GlobalContext
    domain index, score it by how many of its capabilities match the query
    tokens (plus explicit domain-name hits). Returns the strongest domain or
    ``None`` when nothing is clear. Used to narrow the planner's candidate
    space BEFORE the LLM reasons — the LLM never sees unrelated domains.
    """
    try:
        from nexus.context.global_context import get_global_context

        gc = get_global_context()
        domain_index: dict[str, list[str]] = gc.domain_index or {}
        capability_keywords: dict[str, list[str]] = gc.capability_keywords or {}
    except Exception:
        return None

    if not domain_index:
        return None

    q = query.lower().strip()
    tokens = _tokenize_query(q)
    if not tokens:
        return None

    scores: dict[str, float] = {}
    for domain, caps in domain_index.items():
        if not caps:
            continue
        if domain.lower() in q:
            scores[domain] = scores.get(domain, 0) + 5.0
        for cap in caps:
            for tok in tokens:
                # Primary signal: the token is a registered keyword of this
                # capability (O(1) kw_map — the trustworthy, metadata signal).
                if tok in capability_keywords.get(tok, []) and cap in capability_keywords.get(tok, []):
                    scores[domain] = scores.get(domain, 0) + 1.0
                # Secondary: the token IS the FULL capability name (word-for-
                # word). Partial name-token matches ("search" inside
                # "search_anime") are deliberately excluded — generic verbs
                # shared by many tool names inflate every domain and make
                # ties arbitrary.
                elif tok == cap.replace("_", " ").lower().strip():
                    scores[domain] = scores.get(domain, 0) + 1.0

    if not scores:
        return None
    best = max(scores, key=scores.get)
    if scores[best] < 1.0:
        return None
    return best


def _heuristic_classify(
    query: str,
    tool_names: list[str],
    has_workflow_candidates: bool = False,
) -> ExecutionGoals | None:
    """Data-driven fast classification — returns ``None`` if ambiguous.

    Uses ONLY metadata from the registry (capability keyword matches and
    workflow tags from GlobalContext) plus the ResolutionEngine's binary
    workflow fact. Language classification (greetings, knowledge,
    conversation, analysis-vs-action, requirements) is delegated to the LLM
    classifier.

    Rules (applied in order):
    1. Empty query → ``{conversation}``
    2. Workflow-template candidate matched (engine fact) → ``{workflow}``
    3. Capability tagged ``workflow`` in the registry → ``{workflow}``
    4. Any capability candidates → ``{action}`` (task shape is the
       planner+compiler's job — never counted here)
    5. Ambiguous → ``None`` (LLM decides)
    """
    q = query.lower().strip()
    if not q:
        return ExecutionGoals(goals=(ExecutionGoal.CONVERSATION,))

    # WORKFLOW TEMPLATE fact from the ResolutionEngine (single source —
    # the router never re-runs template matching itself).
    if has_workflow_candidates:
        logger.info("router.template_workflow_detected", query=query[:60])
        return ExecutionGoals(goals=(ExecutionGoal.WORKFLOW,))

    # Match query against GlobalContext capability keywords (O(1), data-driven)
    matched_tools = set(tool_names) or _match_capabilities(q)

    # WORKFLOW TAG CHECK — a capability tagged "workflow" in the registry
    # takes priority ONLY when it matched via a DECLARED signal (keyword
    # map), never on bare BM25 noise: the chicken-query-vs-dashboard case
    # (BM25 similarity, no shared intent) must not hijack routing into the
    # workflow manager. Real workflow templates are matched earlier by the
    # engine's ``has_workflow_candidates`` fact (precise trigger patterns).
    keyword_hits = _match_capabilities(q)
    if matched_tools:
        from nexus.context.global_context import get_global_context
        gc = get_global_context()
        for cap_name in matched_tools:
            if cap_name not in keyword_hits:
                continue  # bare BM25 similarity is not a declared signal
            cap_node = gc.compiled_graph.nodes.get(cap_name) if gc.compiled_graph else None
            tags = getattr(cap_node, "tags", []) or []
            if "workflow" in tags:
                logger.info("router.workflow_detected", capability=cap_name, tags=tags)
                return ExecutionGoals(goals=(ExecutionGoal.WORKFLOW,))

    # Any candidate → execution (action). The planner + compiler decide task
    # shape (one node or twenty; dependent or independent) — NOT the router.
    if matched_tools:
        return ExecutionGoals(goals=(ExecutionGoal.ACTION,))

    # No capability matched — ambiguous (greeting, knowledge, conversational,
    # analysis, or needs-requirements): delegate to the LLM classifier.
    return None


from nexus.agent.planners.dependency_analysis import has_schema_dependency as _has_schema_dependency


# ============================================================================
# LLM Classification (Stage 2 — for ambiguous cases)
# ============================================================================

async def _llm_classify(
    query: str,
    tool_names: list[str],
    llm: LLMClient,
    model: str,
) -> ExecutionGoals:
    """Use compact few-shot LLM call to classify ambiguous queries into goals."""
    tools_str = ", ".join(tool_names) if tool_names else "(none)"

    prompt = (
        f"User: {query[:500]}\n"
        f"Candidate capabilities: {tools_str}\n"
        f"Goals and JSON:"
    )

    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": _CLASSIFIER_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=get_settings().agent.router_max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.content or ""
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
            content = re.sub(r"\n```$", "", content)

        parsed = json.loads(content)
        raw_goals = parsed.get("goals") or []
        if isinstance(raw_goals, str):
            raw_goals = [raw_goals]
        needs_req = bool(parsed.get("needs_requirements", False))
        goals = ExecutionGoals.from_values([str(g) for g in raw_goals])
        if not goals.goals:
            logger.warning("router.unrecognized_llm_goals", raw=raw_goals)
            goals = ExecutionGoals(goals=(ExecutionGoal.ACTION,), needs_requirements=needs_req)
        return goals

    except Exception as exc:
        logger.warning("router.llm_classify_failed", error=str(exc))
        # Failure fallback is signal-aware: with NO capability candidates the
        # query carries no tool signal — an unclassified message is answered
        # conversationally, never executed (a greeting must never trigger a
        # tool plan). With candidates, action is the safe side (the planner
        # validates before execution).
        if not tool_names:
            return ExecutionGoals(goals=(ExecutionGoal.CONVERSATION,))
        return ExecutionGoals(goals=(ExecutionGoal.ACTION,))  # safe fallback


# ============================================================================
# Public API
# ============================================================================

async def node_classify_query(
    state: AgentState,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """LangGraph node: classify the user's latest message and set ``_query_type``."""
    messages: list = list(state.get("messages", []))
    last_user = ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break
        if hasattr(m, "role") and getattr(m, "role") == "user":
            last_user = str(getattr(m, "content", ""))
            break

    if not last_user:
        return ExecutionGoals(goals=(ExecutionGoal.CONVERSATION,)).to_state()

    forced = state.get("_force_query_type")
    if forced:
        logger.info("router.forced_type", qtype=forced, query=last_user[:50])
        return ExecutionGoals.from_legacy(forced).to_state()

    # Single resolution pass (ResolutionEngine) — the router consumes binary
    # facts only; the planner later consumes the ranked candidates.
    from nexus.capabilities.resolution_engine import get_resolution_engine

    resolution = await get_resolution_engine().resolve(last_user, top_k=15)
    tool_names = [c.name for c in resolution.capability_candidates]

    goals = await classify_query(
        query=last_user,
        history=messages,
        tool_names=tool_names,
        llm=llm,
        model=model,
        has_workflow_candidates=resolution.has_workflow_candidates,
    )

    result: dict[str, Any] = goals.to_state()
    result["response_type"] = _response_type_for(goals)

    # Domain-first narrowing: a deterministic domain hint from the query is
    # threaded into state so the planner's catalog/Literal is filtered to
    # that domain BEFORE the LLM reasons (capability classification).
    hint = _domain_hint(last_user)
    if hint:
        result["_domain_hint"] = hint
        logger.info("router.domain_hint", query=last_user[:50], domain=hint)

    # Preferred capabilities from the resolved (ranked) candidate stream —
    # the engine's order is preserved.
    if ExecutionGoal.ACTION in goals.goals and tool_names:
        result["_preferred_tools"] = tool_names

    # Intent per goal set (typed downstream consumption).
    from nexus.agent.intent import Intent

    if ExecutionGoal.INFORMATION in goals.goals:
        result["intent"] = Intent(
            query_type="information",
            confidence=0.7,
        ).model_dump()
    elif goals.needs_requirements:
        result["intent"] = await _build_requirements_intent(last_user)
    elif ExecutionGoal.WORKFLOW in goals.goals:
        result["intent"] = Intent(
            query_type="workflow",
            confidence=0.9,
            entities={"raw_query": last_user[:200]},
        ).model_dump()

    return result


def _response_type_for(goals: ExecutionGoals) -> str:
    """Map goals to the response_type consumed by ResponseNode/finalize.

    Values stay compatible with existing consumers (``greeting``/``meta``
    short-circuit the finalize path).
    """
    if goals.needs_requirements:
        return "clarification"
    primary = goals.primary
    if primary == ExecutionGoal.CONVERSATION:
        return "greeting"
    if primary == ExecutionGoal.INFORMATION:
        return "knowledge_only"
    if primary == ExecutionGoal.WORKFLOW:
        return "workflow"
    return ""


async def _build_requirements_intent(
    query: str,
) -> dict[str, Any]:
    """Build an Intent for queries that need requirements gathering.

    Extracts suggested capability from the engine's resolved candidates, and
    sets missing_info slots for the RequirementCollectorNode to fill.
    """
    suggested = None
    try:
        from nexus.capabilities.resolution_engine import get_resolution_engine

        resolution = await get_resolution_engine().resolve(query, top_k=5)
        if resolution.capability_candidates:
            suggested = resolution.capability_candidates[0].name
    except Exception:
        pass
    from nexus.agent.intent import Intent, SlotSpec

    missing: list[SlotSpec] = []
    if not suggested:
        missing.append(SlotSpec(
            name="goal",
            question="What would you like me to help you accomplish?",
        ))

    return Intent(
        query_type="needs_requirements",
        confidence=0.5,
        suggested_capability=suggested,
        missing_info=missing,
    ).model_dump()


async def classify_query(
    query: str,
    history: list[dict[str, Any]] | None = None,
    tool_names: list[str] | None = None,
    llm: LLMClient | None = None,
    model: str | None = None,
    has_workflow_candidates: bool | None = None,
) -> ExecutionGoals:
    """Classify a user query into an ``ExecutionGoals`` set.

    Pipeline:
    0. **Workflow candidates** (ResolutionEngine fact, template-first) → ``{workflow}``
    1. **Data-driven heuristic** (~0ms) — registry capability matches only.
    2. **LLM** (compact few-shot, ~500ms) — decides everything else:
       greetings, knowledge, analysis-vs-action, conversational, requirements.

    Args:
        query: The user query.
        history: Conversation history (follow-up detection).
        tool_names: Candidate capability names from the ResolutionEngine
            (binary facts only — never scores).
        llm: LLM client for stage 2.
        model: Model identifier.
        has_workflow_candidates: Engine fact — a workflow template matched.
    """
    # Stage 0: workflow-template fact (the engine already matched templates —
    # the router never re-runs template matching itself).
    if has_workflow_candidates is None:
        try:
            from nexus.capabilities.resolution_engine import get_resolution_engine

            resolution = await get_resolution_engine().resolve(query, top_k=15)
            has_workflow_candidates = resolution.has_workflow_candidates
            tool_names = [c.name for c in resolution.capability_candidates]
        except Exception as exc:
            logger.warning("router.resolve_failed", error=str(exc)[:200])

    # Stage 1: Heuristic
    tool_names_list = tool_names or []
    heuristic_result = _heuristic_classify(
        query,
        tool_names_list,
        has_workflow_candidates=bool(has_workflow_candidates),
    )

    if heuristic_result is not None:
        logger.info(
            "router.heuristic_classified",
            query=query[:50],
            goals=heuristic_result.values,
        )
        return heuristic_result

    # Stage 2: LLM fallback
    if llm is not None and model is not None:
        llm_result = await _llm_classify(query, tool_names_list, llm, model)
        logger.info(
            "router.llm_classified",
            query=query[:50],
            goals=llm_result.values,
        )
        return llm_result

    # Fallback
    logger.info("router.default_classified", query=query[:50])
    return ExecutionGoals(goals=(ExecutionGoal.ACTION,))



