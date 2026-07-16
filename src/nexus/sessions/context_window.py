"""Context window management — token counting, summarization, message assembly."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import structlog
import tiktoken

from nexus.config.settings import AgentSettings, get_settings
from nexus.db.models.session import Message as MessageModel
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.sessions.context_window")

_SUMMARIZATION_PROMPT = (
    "Summarize the following conversation to preserve key facts, decisions, "
    "user preferences, and results. Omit greetings and chit-chat. "
    "Keep the summary concise but comprehensive:"
)

_ENCODING_CACHE: dict[str, str] = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "claude-3-opus": "cl100k_base",
    "claude-3-sonnet": "cl100k_base",
    "claude-3-haiku": "cl100k_base",
    "claude-3.5-sonnet": "cl100k_base",
    "claude-4": "cl100k_base",
    "gemini-pro": "cl100k_base",
    "gemini-1.5-pro": "cl100k_base",
    "gemini-2.0-flash": "cl100k_base",
}

_DEFAULT_ENCODING = "cl100k_base"


def _get_encoding(model: str) -> tiktoken.Encoding:
    """Return the appropriate tiktoken encoding for a given model name."""
    encoding_name = _DEFAULT_ENCODING
    for prefix, enc in _ENCODING_CACHE.items():
        if model.startswith(prefix):
            encoding_name = enc
            break
    return tiktoken.get_encoding(encoding_name)


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count the number of tokens in a text string for the given model."""
    encoding = _get_encoding(model)
    return len(encoding.encode(text))


def _message_to_text(msg: MessageModel) -> str:
    """Convert a Message DB model to plain text for token counting.

    Builds a short string like::

        user: Hello
        assistant: Hi there
    """
    role = msg.role
    content = msg.content or {}
    text = content.get("text") or content.get("content") or ""
    tool_str = ""
    if msg.tool_calls:
        tool_names = [tc.get("function", {}).get("name", "?") for tc in msg.tool_calls]
        tool_str = f" [tool_calls: {', '.join(tool_names)}]"
    return f"{role}: {text}{tool_str}"


def messages_token_count(messages: Sequence[MessageModel], model: str = "gpt-4o") -> int:
    """Count total tokens for a sequence of messages."""
    total = 0
    for msg in messages:
        total += count_tokens(_message_to_text(msg), model)
    return total


def _message_to_openai(msg: MessageModel) -> dict[str, Any]:
    """Convert a Message DB model to OpenAI-format dict for LLM consumption.

    Returns dict with role, content, and optional tool_calls.
    """
    entry: dict[str, Any] = {
        "role": msg.role,
        "content": msg.content.get("text") if msg.content else None,
    }
    if msg.tool_calls:
        entry["tool_calls"] = msg.tool_calls
    if msg.role == "tool":
        tool_call_id = (msg.content.get("tool_call_id") if msg.content else None) or msg.tool_calls[
            0
        ]["id"]
        entry["tool_call_id"] = tool_call_id
    return entry


class ContextWindowManager:
    """Assembles messages for LLM input with automatic summarization.

    When the total token count exceeds ``summarization_threshold_tokens``,
    older messages are summarized into a single system message with
    ``kind=summary``.  The following are always preserved:
      - system prompt messages (role=system, kind!=summary)
      - the last ``preserve_last_n`` messages (default 20)
      - any message with pending tool calls
      - any message referenced by the current plan
    """

    def __init__(
        self,
        llm_client: LLMClient,
        model: str | None = None,
        settings: AgentSettings | None = None,
        preserve_last_n: int = 20,
    ) -> None:
        self._llm = llm_client
        self._model = model or get_settings().llm.default_model
        self._settings = settings or get_settings().agent
        self._preserve_last_n = preserve_last_n

    def _should_summarize(self, messages: Sequence[MessageModel]) -> bool:
        """Check if total tokens exceed the summarization threshold."""
        total = messages_token_count(messages, self._model)
        return total > self._settings.summarization_threshold_tokens

    def _identify_preserved_indices(
        self,
        messages: Sequence[MessageModel],
        plan: list[dict[str, Any]] | None = None,
    ) -> set[int]:
        """Return the set of message indices that must be preserved as-is."""
        preserved: set[int] = set()

        for i, msg in enumerate(messages):
            if msg.role == "system":
                kind = (msg.content or {}).get("kind")
                if kind != "summary":
                    preserved.add(i)

        n = len(messages)
        last_start = max(0, n - self._preserve_last_n)
        for i in range(last_start, n):
            preserved.add(i)

        for i, msg in enumerate(messages):
            if msg.tool_calls and msg.tool_calls != []:
                preserved.add(i)

        if plan:
            referenced_ids: set[str] = set()
            for step in plan:
                inputs = step.get("inputs") or {}
                for val in inputs.values():
                    if isinstance(val, str) and val.startswith("msg:"):
                        referenced_ids.add(val[4:])

            for i, msg in enumerate(messages):
                if str(msg.id) in referenced_ids:
                    preserved.add(i)

        return preserved

    async def assemble(
        self,
        messages: Sequence[MessageModel],
        plan: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Assemble messages for LLM input, summarizing if needed.

        Args:
            messages: All messages in the session (ordered by created_at).
            plan: Optional current plan steps (for reference preservation).

        Returns:
            List of OpenAI-format message dicts ready for the LLM.
        """
        if not self._should_summarize(messages):
            return [_message_to_openai(m) for m in messages]

        preserved = self._identify_preserved_indices(messages, plan)

        to_summarize: list[MessageModel] = []
        preserved_msgs: list[MessageModel] = []
        for i, msg in enumerate(messages):
            if i in preserved:
                preserved_msgs.append(msg)
            else:
                to_summarize.append(msg)

        if not to_summarize:
            return [_message_to_openai(m) for m in messages]

        summary_text = await self._summarize(to_summarize)

        summary_msg = MessageModel(
            id=uuid.uuid4(),
            session_id=messages[0].session_id if messages else uuid.uuid4(),
            role="system",
            content={"text": summary_text, "kind": "summary"},
        )

        result = [_message_to_openai(summary_msg)]
        result.extend(_message_to_openai(m) for m in preserved_msgs)

        return result

    async def _summarize(self, messages: Sequence[MessageModel]) -> str:
        """Call the LLM to summarize a list of messages into a single string."""
        text_parts = [_message_to_text(m) for m in messages]
        full_text = "\n".join(text_parts)

        summarization_messages: list[dict[str, str]] = [
            {"role": "system", "content": _SUMMARIZATION_PROMPT},
            {"role": "user", "content": full_text},
        ]

        response = await self._llm.complete(
            model=self._model,
            messages=summarization_messages,
            temperature=0.3,
            max_tokens=2048,
        )
        summary = response.content or ""
        logger.info(
            "summarized_messages",
            count=len(messages),
            summary_length=len(summary),
            model=self._model,
        )
        return summary
