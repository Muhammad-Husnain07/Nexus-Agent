"""WorkingMemory — session-scoped structured scratchpad across conversation turns.

Working memory persists within a conversation session (via LangGraph checkpointer)
but is ephemeral across sessions. High-importance entries are automatically promoted
to long-term memory on session end.

Each entry has: key, content, source (user_message|tool_result|inference|reflection),
turn_id, and importance score.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from nexus.config.settings import get_settings

logger = structlog.get_logger("nexus.memory.working")

WM_SOURCES = frozenset({"user_message", "tool_result", "inference", "reflection", "slot_resolved"})


def _format_wm_entry(entry: dict[str, Any], max_chars: int = 500) -> str:
    """Format a single working memory entry as XML."""
    key = entry.get("key", "unknown")
    content = entry.get("content", "")
    source = entry.get("source", "inference")
    if len(content) > max_chars:
        content = content[:max_chars] + "..."
    return f'<entry key="{key}" source="{source}">{content}</entry>'


class WorkingMemory:
    """Session-scoped key-value working memory.

    Accumulates information across turns within a conversation.
    Automatically evicts lowest-importance entries when over capacity.
    """

    def __init__(self, entries: list[dict[str, Any]] | None = None) -> None:
        self.entries: list[dict[str, Any]] = list(entries) if entries else []

    def add(
        self,
        key: str,
        content: str,
        source: str = "inference",
        importance: float = 0.5,
        turn_id: int = 0,
    ) -> None:
        """Add an entry, updating existing if key already exists."""
        if source not in WM_SOURCES:
            source = "inference"

        # Update existing entry with matching key
        for entry in self.entries:
            if entry.get("key") == key:
                entry["content"] = content
                entry["source"] = source
                entry["turn_id"] = turn_id
                entry["importance"] = max(entry.get("importance", 0), importance)
                return

        self.entries.append({
            "key": key,
            "content": content,
            "source": source,
            "turn_id": turn_id,
            "importance": importance,
        })

        self._evict_if_needed()

    def get(self, key: str) -> list[dict[str, Any]]:
        """Retrieve all entries matching a key prefix."""
        return [e for e in self.entries if e.get("key", "").startswith(key)]

    def search(self, text: str) -> list[dict[str, Any]]:
        """Text search across keys and content."""
        text_lower = text.lower()
        return [
            e for e in self.entries
            if text_lower in e.get("key", "").lower()
            or text_lower in e.get("content", "").lower()
        ]

    def to_context(self, n: int = 10, max_chars_per_entry: int = 500) -> str:
        """Format last N entries as an XML block for prompt injection."""
        if not self.entries:
            return ""
        recent = self.entries[-n:]
        parts = ["<working_memory>"]
        for entry in reversed(recent):
            parts.append(_format_wm_entry(entry, max_chars=max_chars_per_entry))
        parts.append("</working_memory>")
        return "\n".join(parts)

    def high_importance_entries(self, threshold: float = 0.7) -> list[dict[str, Any]]:
        """Return entries above the importance threshold (for LTM promotion)."""
        return [e for e in self.entries if e.get("importance", 0) >= threshold]

    def summarize(self, llm: Any = None) -> None:
        """Compress working memory when over capacity.

        Keeps highest-importance entries. If an LLM is provided, also
        generates a condensed summary of evicted entries.
        """
        max_entries = getattr(get_settings().memory, "working_memory_max_entries", 50)
        if len(self.entries) <= max_entries:
            return

        # Sort by importance desc, keep top max_entries
        self.entries.sort(key=lambda e: e.get("importance", 0), reverse=True)
        evicted = self.entries[max_entries:]
        self.entries = self.entries[:max_entries]

        if evicted and llm is not None:
            try:
                summary = self._eviction_summary(evicted)
                if summary:
                    self.entries.append({
                        "key": "_summary",
                        "content": summary,
                        "source": "inference",
                        "turn_id": max(e.get("turn_id", 0) for e in self.entries),
                        "importance": 0.3,
                    })
            except Exception:
                pass

        logger.info("working_memory.evicted", count=len(evicted))

    def _evict_if_needed(self) -> None:
        """Remove lowest-importance entries when over capacity."""
        max_entries = getattr(get_settings().memory, "working_memory_max_entries", 50)
        if len(self.entries) <= max_entries:
            return
        self.entries.sort(key=lambda e: e.get("importance", 0), reverse=True)
        self.entries = self.entries[:max_entries]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for AgentState storage."""
        return {
            "entries": [
                {
                    "key": e["key"],
                    "content": e["content"],
                    "source": e["source"],
                    "turn_id": e["turn_id"],
                    "importance": e["importance"],
                }
                for e in self.entries
            ],
        }

    @staticmethod
    def from_dict(data: dict[str, Any] | None) -> WorkingMemory:
        """Deserialize from AgentState dict."""
        if not data:
            return WorkingMemory()
        return WorkingMemory(entries=data.get("entries", []))

    @staticmethod
    def _eviction_summary(evicted: list[dict[str, Any]]) -> str:
        """Generate a one-line summary of evicted entries."""
        keys = [e["key"] for e in evicted if "key" in e]
        return f"Previously discussed: {', '.join(keys[:5])}"
