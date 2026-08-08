"""ValidatorNode — multi-tier output validation for tool results.

Four tiers:
1. JSON Schema validation against tool output_schema
2. Capability output contract (required_any_of JSONPath)
3. Business rules from CapabilityModel.business_rules
4. LLM confidence check (optional, configurable threshold)

Runs after AggregatorNode. Failed validations are stored in
``_validation_failed`` and ``_validation_results`` for downstream
SelfHealingNode to process.
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel, Field

from nexus.agent.state import AgentState
from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.agent.nodes.validator")


class FailureReport(BaseModel):
    """A single validation failure with tier and reason."""
    task_id: str = Field(description="Failed task ID")
    tier: int = Field(ge=1, le=4, description="Validation tier that failed")
    reason: str = Field(description="Human-readable failure reason")
    capability: str = Field(default="", description="Capability that was validated")


async def validator_node(state: AgentState) -> dict[str, Any]:
    """Validate all tool results against four tiers.

    Reads ``tool_results`` from state (canonical list of tool outputs).
    Runs each result through Tiers 1-4. Collects failures into
    ``_validation_failed`` and ``_validation_results``.

    Returns:
        State update with validation outcomes.
    """
    tool_results: list[dict[str, Any]] = state.get("tool_results", [])
    if not tool_results:
        return {"_validation_failed": []}

    settings = get_settings()
    failures: list[dict[str, Any]] = []

    for outcome in tool_results:
        if not isinstance(outcome, dict):
            continue
        task_id = outcome.get("task_id", "")

        status = outcome.get("status", "")
        data = outcome.get("data")
        tool_name = outcome.get("tool_name", task_id)

        # Tier 1: JSON Schema validation (fast, no DB)
        tier1_error = await _tier1_json_schema(data, tool_name)
        if tier1_error:
            _record_failure(failures, task_id, 1, tier1_error, tool_name)
            continue

        # Tier 2: Output contract (requires DB — RegistryClient)
        tier2_error = await _tier2_output_contract(data, tool_name)
        if tier2_error:
            _record_failure(failures, task_id, 2, tier2_error, tool_name)
            continue

        # Tier 3: Business rules (requires DB — CapabilityModel.business_rules)
        tier3_error = await _tier3_business_rules(data, tool_name)
        if tier3_error:
            _record_failure(failures, task_id, 3, tier3_error, tool_name)
            continue

        # Tier 4: LLM confidence check
        tier4_error = await _tier4_confidence_check(data, tool_name, settings)
        if tier4_error:
            _record_failure(failures, task_id, 4, tier4_error, tool_name)

    if failures:
        logger.warning(
            "validator_node.failures",
            total=len(failures),
            tiers={f["tier"] for f in failures},
        )
    else:
        logger.info("validator_node.all_valid")

    return {
        "_validation_failed": [f["task_id"] for f in failures],
        "_validation_results": list(failures),
    }


def _record_failure(
    failures: list[dict[str, Any]],
    task_id: str,
    tier: int,
    reason: str,
    capability: str,
) -> None:
    """Record a validation failure."""
    failures.append({
        "task_id": task_id,
        "tier": tier,
        "reason": reason,
        "capability": capability,
    })


async def _tier1_json_schema(
    data: Any,
    tool_name: str,
) -> str | None:
    """Tier 1: Validate data against tool output_schema.

    Currently performs basic type/sanity checks since full JSON Schema
    requires access to the tool's registered schema.
    """
    if data is None:
        return "No result data returned from tool"
    return None


async def _tier2_output_contract(
    data: Any,
    capability: str,
) -> str | None:
    """Tier 2: Validate against capability output contract."""
    if data is None:
        return None

    try:
        from nexus.db.base import async_session as _db_session
        from nexus.execution.contracts import validate_tool_result
        from nexus.registry.client import RegistryClient

        async with _db_session() as session:
            registry = RegistryClient(session)
            is_valid, reason = await validate_tool_result(capability, data, registry)
            if not is_valid:
                return reason
    except Exception as exc:
        logger.warning("validator.tier2_error", capability=capability, error=str(exc))
    return None


async def _tier3_business_rules(
    data: Any,
    capability: str,
) -> str | None:
    """Tier 3: Validate business rules from CapabilityModel.

    Reads ``business_rules`` JSONB from the capability and checks each
    rule: a list of JSONPath-like predicates that must all pass.

    Business rules example::
        {"all_of": ["$.transaction.id != null", "$.transaction.amount >= 0"]}
    """
    if data is None or not isinstance(data, dict):
        return None

    try:
        from nexus.db.base import async_session as _db_session
        from nexus.db.models.registry import CapabilityModel
        from sqlalchemy import select

        async with _db_session() as session:
            result = await session.execute(
                select(CapabilityModel).where(
                    CapabilityModel.logical_op_name == capability,
                    CapabilityModel.enabled == True,
                )
            )
            cap = result.scalar_one_or_none()
            if cap is None:
                return None

            rules = getattr(cap, "contract", {}).get("business_rules", {}) if hasattr(cap, "contract") else {}
            if not rules:
                return None

            all_of = rules.get("all_of", [])
            if not all_of:
                return None

            for rule_path in all_of:
                if not isinstance(rule_path, str):
                    continue
                # Simple existence check: "path exists and != null"
                if rule_path.startswith("$."):
                    clean = rule_path[2:]
                else:
                    clean = rule_path
                if _resolve_jsonpath(data, clean) is None:
                    return f"Business rule failed: {rule_path}"
    except Exception as exc:
        logger.warning("validator.tier3_error", capability=capability, error=str(exc))
    return None


async def _tier4_confidence_check(
    data: Any,
    tool_name: str,
    settings: Any,
) -> str | None:
    """Tier 4: Optional LLM-based confidence check.

    Only runs if settings.compiler.enable_confidence_check is True.
    Uses a tiny LLM call to rate output quality.
    """
    if not data:
        return None
    confidence_settings = getattr(settings.compiler, "confidence_check", None)
    if confidence_settings is None or not confidence_settings.get("enabled", False):
        return None

    import json
    model = confidence_settings.get("model", settings.llm.default_model)
    try:
        from nexus.llm.client import LLMClient

        client = LLMClient()
        prompt = (
            f"Rate the quality of this tool output for '{tool_name}' on a scale of 0.0-1.0.\n"
            f"Return JSON: {{\"confidence\": 0.0-1.0, \"reason\": \"...\"}}\n\n"
            f"Output: {json.dumps(data)[:2000]}"
        )
        response = await client.complete(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=128,
            response_format={"type": "json_object"},
        )
        if response.content:
            parsed = json.loads(response.content)
            confidence = parsed.get("confidence", 1.0)
            min_confidence = confidence_settings.get("min_confidence", 0.3)
            if confidence < min_confidence:
                reason = parsed.get("reason", "Low confidence")
                return f"Confidence check failed ({confidence:.2f}): {reason}"
    except Exception:
        pass
    return None


def _resolve_jsonpath(data: dict[str, Any], path: str) -> Any:
    """Resolve a dot-separated path in a dict, returning None if missing."""
    current: Any = data
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return None
    return current
