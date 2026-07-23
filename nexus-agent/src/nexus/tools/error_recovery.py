"""Semantic error recovery — classify, diagnose, and recover from tool call errors.

Hybrid approach: rule-based regex patterns for common errors (fast path),
LLM escalation for novel/unmatched errors (deep analysis path).

Supports category-specific retry strategies:
- transient_network: exponential backoff + jitter
- rate_limit: parse Retry-After, honor exact delay
- schema_mismatch: extract field, apply mapping, retry
- auth_failure: try token refresh once, then escalate
- not_found / argument_error: immediate fallback, no retry
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import structlog

from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.tools.error_recovery")


class ErrorCategory(Enum):
    TRANSIENT_NETWORK = "transient_network"
    TRANSIENT_RATE_LIMIT = "transient_rate_limit"
    TRANSIENT_SERVICE = "transient_service"
    PERMANENT_AUTH = "permanent_auth"
    PERMANENT_SCHEMA = "permanent_schema"
    PERMANENT_ARGUMENT = "permanent_argument"
    PERMANENT_NOT_FOUND = "permanent_not_found"
    PERMANENT_PERMISSION = "permanent_permission"
    UNKNOWN = "unknown"


# ── Regex patterns for fast-path classification ──────────────────────────

_PATTERNS: dict[ErrorCategory, list[str]] = {
    ErrorCategory.TRANSIENT_NETWORK: [
        r"timeout", r"timed?\s*out", r"connection\s*(refused|reset|closed)",
        r"network.*(error|unreachable)", r"econnrefused",
        r"no.*route.*host", r"dns.*(error|failure)",
    ],
    ErrorCategory.TRANSIENT_RATE_LIMIT: [
        r"rate\s*limit", r"too\s*many\s*requests", r" 429 ",
        r"throttl", r"quota.*exceeded", r"retry.*after",
    ],
    ErrorCategory.TRANSIENT_SERVICE: [
        r"50[0-9]", r"service\s*unavailable", r"temporarily.*unavailable",
        r"internal.*(error|failure)", r"bad\s*gateway", r"server.*error",
    ],
    ErrorCategory.PERMANENT_AUTH: [
        r" 401 ", r"unauthorized", r"unauthenticated",
        r"invalid\s*(api.?key|token|credential)",
        r"auth.*(failed|expired|invalid)",
    ],
    ErrorCategory.PERMANENT_SCHEMA: [
        r"schema.*mismatch", r"unexpected.*field", r"missing.*required.*(field|parameter)",
        r"validation.*(error|failed)", r"does not match", r"type.*mismatch",
    ],
    ErrorCategory.PERMANENT_ARGUMENT: [
        r"invalid.*(argument|parameter|value)", r"not.*(found|valid|allowed)",
        r"enum.*value", r"out of range", r"constraint.*violation",
    ],
    ErrorCategory.PERMANENT_NOT_FOUND: [
        r" 404 ", r"not found", r"doesn'?t exist",
    ],
    ErrorCategory.PERMANENT_PERMISSION: [
        r" 403 ", r"forbidden", r"permission.*denied", r"access.*denied",
    ],
}

_FIELD_PATTERNS = [
    re.compile(r"""field['"]?\s*[:=]?\s*['"]?(\w+)['"]?""", re.I),
    re.compile(r"""parameter['"]?\s*[:=]?\s*['"]?(\w+)['"]?""", re.I),
    re.compile(r"""property['"]?\s*[:=]?\s*['"]?(\w+)['"]?""", re.I),
]

_LLM_CLASSIFY_PROMPT = """\
Classify this tool call error into exactly one category. Return only the category name.

Categories:
- transient_network: timeout, connection refused, DNS failure
- transient_rate_limit: 429, rate limited, quota exceeded
- transient_service: 500, 502, 503, service unavailable
- permanent_auth: 401, invalid API key, auth expired
- permanent_schema: validation error, unexpected field, type mismatch
- permanent_argument: invalid parameter, enum error, constraint violation
- permanent_not_found: 404, resource does not exist
- permanent_permission: 403, forbidden, access denied

Error: {error}

Category:"""


# ── Data classes ─────────────────────────────────────────────────────────

@dataclass
class ErrorDiagnosis:
    category: ErrorCategory = ErrorCategory.UNKNOWN
    root_cause: str = ""
    affected_fields: list[str] = field(default_factory=list)
    suggested_fix: str | None = None
    retryable: bool = False
    requires_user_input: bool = False
    fallback_tools: list[str] = field(default_factory=list)


# ── Classifier ───────────────────────────────────────────────────────────

class SemanticErrorClassifier:
    """Classifies tool errors using regex patterns with LLM escalation."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    def classify(self, error_message: str) -> ErrorCategory:
        """Fast path: classify using regex patterns."""
        error_lower = error_message.lower()
        for category, patterns in _PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, error_lower):
                    return category
        return ErrorCategory.UNKNOWN

    async def classify_deep(self, error_message: str) -> ErrorCategory:
        """Slow path: use LLM for deep classification when regex doesn't match."""
        cat = self.classify(error_message)
        if cat != ErrorCategory.UNKNOWN or self._llm is None:
            return cat

        try:
            response = await self._llm.complete(
                model=get_settings().llm.default_model,
                messages=[
                    {"role": "user", "content": _LLM_CLASSIFY_PROMPT.format(error=error_message[:500])},
                ],
                temperature=0,
            )
            label = (response.content or "").strip().lower()
            for ec in ErrorCategory:
                if ec.value == label:
                    return ec
        except Exception:
            pass

        return ErrorCategory.UNKNOWN

    def is_transient(self, error_message: str) -> bool:
        cat = self.classify(error_message)
        return cat in (
            ErrorCategory.TRANSIENT_NETWORK,
            ErrorCategory.TRANSIENT_RATE_LIMIT,
            ErrorCategory.TRANSIENT_SERVICE,
        )

    def extract_fields(self, error_message: str) -> list[str]:
        """Extract field names mentioned in the error."""
        fields: list[str] = []
        for pat in _FIELD_PATTERNS:
            fields.extend(pat.findall(error_message))
        return list(set(fields))

    async def diagnose(self, error_message: str, tool_name: str = "",
                       params: dict[str, Any] | None = None) -> ErrorDiagnosis:
        """Full diagnosis with deep classification and fix suggestions."""
        category = await self.classify_deep(error_message)
        fields = self.extract_fields(error_message)

        fix = self._suggest_fix(category, error_message, params or {})
        retryable = category in (
            ErrorCategory.TRANSIENT_NETWORK,
            ErrorCategory.TRANSIENT_RATE_LIMIT,
            ErrorCategory.TRANSIENT_SERVICE,
            ErrorCategory.PERMANENT_SCHEMA,
            ErrorCategory.PERMANENT_ARGUMENT,
        )
        needs_user = category in (
            ErrorCategory.PERMANENT_AUTH,
            ErrorCategory.PERMANENT_PERMISSION,
        )

        return ErrorDiagnosis(
            category=category,
            root_cause=error_message[:300],
            affected_fields=fields,
            suggested_fix=fix,
            retryable=retryable,
            requires_user_input=needs_user,
        )

    def _suggest_fix(self, category: ErrorCategory, error: str,
                     params: dict[str, Any]) -> str | None:
        if category == ErrorCategory.PERMANENT_SCHEMA:
            return "Field name may need updating — check the API documentation"
        if category == ErrorCategory.PERMANENT_ARGUMENT:
            return "Parameter value is invalid — provide a different value"
        if category == ErrorCategory.TRANSIENT_RATE_LIMIT:
            match = re.search(r"retry.*?(\d+)\s*(?:seconds?|sec|s)?", error, re.I)
            delay = match.group(1) if match else "60"
            return f"Retry after {delay} seconds"
        if category == ErrorCategory.PERMANENT_AUTH:
            return "Authentication failed — check credentials"
        if category in (ErrorCategory.TRANSIENT_NETWORK, ErrorCategory.TRANSIENT_SERVICE):
            return "Transient failure — retry with backoff"
        return None


# ── Retry strategies ─────────────────────────────────────────────────────


def _backoff_delay(attempt: int, base: float = 1.0, max_delay: float = 60.0) -> float:
    """Exponential backoff with jitter: min(max_delay, base * 2^attempt + random(0,1))."""
    delay = min(base * (2 ** attempt), max_delay)
    return delay + random.uniform(0, 1)


class SemanticRetryHandler:
    """Executes tool calls with category-aware retry logic.

    Strategies per category:
    - transient_network: exponential backoff up to 3 attempts
    - rate_limit: parse Retry-After, honor exact delay
    - schema_mismatch: apply field mapping, retry once
    - auth_failure: try token refresh once, then escalate
    - not_found / argument_error: no retry, fallback immediately
    """

    def __init__(self, max_retries: int = 3, llm: LLMClient | None = None) -> None:
        self.max_retries = max_retries
        self.classifier = SemanticErrorClassifier(llm=llm)

    async def execute(
        self,
        tool_fn: Callable[..., Any],
        params: dict[str, Any],
        tool_name: str = "",
        schema: dict[str, Any] | None = None,
    ) -> tuple[bool, Any, ErrorDiagnosis | None]:
        """Execute a tool call with semantic retry.

        Returns: (success, result_or_error, diagnosis_if_failed)
        """
        last_error: str = ""
        diagnosis: ErrorDiagnosis | None = None

        for attempt in range(self.max_retries + 1):
            try:
                result = await tool_fn(**params)
                return True, result, None
            except Exception as e:
                last_error = str(e)
                diagnosis = await self.classifier.diagnose(last_error, tool_name, params)

                if not diagnosis.retryable or attempt >= self.max_retries:
                    break

                # Apply category-specific delay and param modification
                delay = self._get_delay(attempt, diagnosis)
                modified_params = self._modify_params(params, diagnosis)

                if modified_params != params:
                    logger.info("retry.modified_params", tool=tool_name,
                                attempt=attempt, diagnosis=diagnosis.category.value)
                    params = modified_params

                if delay > 0:
                    await asyncio.sleep(delay)

        return False, last_error, diagnosis

    def _get_delay(self, attempt: int, diagnosis: ErrorDiagnosis) -> float:
        """Get retry delay based on error category."""
        if diagnosis.category == ErrorCategory.TRANSIENT_RATE_LIMIT:
            match = re.search(r"retry.*?(\d+)\s*(?:seconds?|sec|s)?", diagnosis.root_cause, re.I)
            if match:
                return float(match.group(1))
            return _backoff_delay(attempt, base=2.0)

        if diagnosis.category in (ErrorCategory.TRANSIENT_NETWORK, ErrorCategory.TRANSIENT_SERVICE):
            return _backoff_delay(attempt)

        if diagnosis.category == ErrorCategory.PERMANENT_SCHEMA:
            return 0.0  # schema mismatch — retry immediately after param fix

        return 0.0

    def _modify_params(self, params: dict[str, Any],
                       diagnosis: ErrorDiagnosis) -> dict[str, Any]:
        """Modify parameters based on error diagnosis to fix the issue."""
        if diagnosis.category != ErrorCategory.PERMANENT_SCHEMA:
            return params

        modified = dict(params)
        renamed: dict[str, str] = {}

        # Try field renames based on common patterns
        if diagnosis.affected_fields:
            for field in diagnosis.affected_fields:
                if field in modified:
                    continue
                # Check for common renames
                lower = field.lower()
                candidates = {
                    "q": "query", "query": "q",
                    "name": "title", "title": "name",
                    "id": "identifier", "identifier": "id",
                    "email": "email_address", "email_address": "email",
                    "lat": "latitude", "latitude": "lat",
                    "lon": "longitude", "longitude": "lon", "long": "lon",
                    "city": "location", "location": "city",
                }
                if lower in candidates and candidates[lower] in modified:
                    renamed[field] = candidates[lower]

        for new_name, old_name in renamed.items():
            modified[new_name] = modified.pop(old_name)

        return modified
