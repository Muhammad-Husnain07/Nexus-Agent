"""EpisodicSummarizer — compresses a finished agent run into a concise summary.

Uses the configured LLM to produce a 3-5 sentence episodic memory entry from
the agent's conversation history, tool results, and final outcome.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.config.settings import get_settings
from nexus.llm.client import LLMClient, LLMResponse

logger = structlog.get_logger("nexus.memory.summarizer")

_SUMMARIZE_SYSTEM_PROMPT = """\
You are an episodic memory summarizer. Given the transcript of an agent run,
produce a concise 3-5 sentence summary that captures:

1. What the user asked for (the goal)
2. What tools were called and key results
3. Any important decisions, preferences, or facts discovered
4. The final outcome (success, failure, partial)

Focus on information that would be useful for future interactions with the
same user.  Omit transient details like exact timestamps, error codes, or
intermediate steps that have no lasting value.

Return ONLY the summary text — no preamble, no markdown formatting.
"""


class EpisodicSummarizer:
    """Compresses agent run state into a short episodic memory entry."""

    def __init__(self, llm: LLMClient | None = None, model: str | None = None) -> None:
        self._llm = llm or LLMClient()
        settings = get_settings()
        self._model = model or settings.llm.default_model

    async def summarize(self, agent_state: dict[str, Any]) -> str:
        """Produce a 3-5 sentence summary from the agent's final state.

        Args:
            agent_state: The ``AgentState`` dict after a completed run.

        Returns:
            A short natural-language summary string.
        """
        transcript = self._build_transcript(agent_state)

        response: LLMResponse = await self._llm.complete(
            model=self._model,
            messages=[
                {"role": "system", "content": _SUMMARIZE_SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            temperature=0.3,
        )

        summary = (response.content or "").strip()
        if not summary:
            summary = "Agent run completed with no notable outcomes."
            logger.warning("summarizer.empty_summary")
        return summary

    @staticmethod
    def _build_transcript(agent_state: dict[str, Any]) -> str:
        """Build a compact transcript from agent state for the LLM."""
        messages = agent_state.get("messages", [])
        tool_results = agent_state.get("tool_results", [])
        plan = agent_state.get("plan", [])
        errors = agent_state.get("errors", [])
        intent = agent_state.get("intent", {})

        parts = [f"User intent: {json.dumps(intent)}"]

        if messages:
            last_user = next(
                (m["content"] for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            parts.append(f"User message: {last_user[:500]}")

        if plan:
            step_descriptions = [
                f"  - {s.get('description', '?')} ({s.get('tool_name', 'none')})"
                for s in plan
            ]
            parts.append("Plan steps:\n" + "\n".join(step_descriptions))

        if tool_results:
            last_result = tool_results[-1]
            parts.append(
                f"Last tool result: {last_result.get('tool_name', '?')} → "
                f"{last_result.get('status', '?')}"
            )

        if errors:
            parts.append(f"Errors encountered: {'; '.join(errors[-3:])}")

        return "\n\n".join(parts)
