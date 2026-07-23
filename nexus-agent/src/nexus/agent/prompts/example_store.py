"""ExampleStore — dynamic example selection for prompt templates.

Loads curated example pools from YAML files and selects the most relevant
examples based on the current query context (e.g. response_type, intent category).
Uses tag-based matching for deterministic, predictable selection.

Usage::

    from nexus.agent.prompts.example_store import ExampleStore

    store = ExampleStore()
    examples = store.select("understand_intent", {"response_type": "tool", "intent": "weather"})
"""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger("nexus.agent.prompts.example_store")

_EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"

_PROMPT_FILE_MAP: dict[str, str] = {
    "understand_intent": "understand_intent.yaml",
    "plan_parallel": "plan_parallel.yaml",
    "gather_requirements": "gather_requirements.yaml",
    "finalize": "finalize.yaml",
    "reflect_on_response": "reflect_on_response.yaml",
    "plan": "plan.yaml",
    "execute_step": "execute_step.yaml",
    "analyze_results": "analyze_results.yaml",
    "execute_step_correction": "execute_step.yaml",
    "execute_step_error_recovery": "execute_step.yaml",
    "execute_step_approval": "execute_step.yaml",
    "analyze_results_enriched": "analyze_results.yaml",
}


def _format_example(example: dict[str, Any]) -> str:
    """Format a single example as an XML block for prompt injection."""
    lines: list[str] = []
    lines.append(f'<example index="{example.get("index", 1)}" category="{example.get("category", "general")}">')
    if example.get("input"):
        lines.append(f"<input>{example['input']}</input>")
    if example.get("thinking"):
        lines.append(f"<thinking>{example['thinking']}</thinking>")
    if example.get("output"):
        lines.append(f"<output>{example['output']}</output>")
    if example.get("wrong_output"):
        lines.append(f"<wrong_output>{example['wrong_output']}</wrong_output>")
        lines.append(f"<correction>{example.get('correction', 'See correct output above')}</correction>")
    lines.append("</example>")
    return "\n".join(lines)


def _format_examples(examples: list[dict[str, Any]]) -> str:
    """Format a list of examples into an XML <examples> block."""
    if not examples:
        return ""
    blocks = [_format_example(ex) for ex in examples]
    return "<examples>\n" + "\n".join(blocks) + "\n</examples>"


def _format_common_mistakes(mistakes: list[dict[str, Any]]) -> str:
    """Format common mistakes into an XML <common_mistakes> block."""
    if not mistakes:
        return ""
    blocks: list[str] = []
    for m in mistakes:
        blocks.append(
            f'<mistake id="{m.get("id", "m1")}" name="{m.get("name", "unknown")}">\n'
            f"<scenario>{m.get('scenario', '')}</scenario>\n"
            f"<wrong>{m.get('wrong', '')}</wrong>\n"
            f"<right>{m.get('right', '')}</right>\n"
            f"<explanation>{m.get('explanation', '')}</explanation>\n"
            f"</mistake>"
        )
    return "<common_mistakes>\n" + "\n".join(blocks) + "\n</common_mistakes>"


class ExampleStore:
    """Loads, indexes, and selects examples from YAML pools.

    Examples are loaded lazily on first access per prompt name.
    Selection uses tag-based matching against the provided context dict.
    """

    def __init__(self, examples_dir: str | Path | None = None) -> None:
        self._examples_dir = Path(examples_dir) if examples_dir else _EXAMPLES_DIR
        self._pools: dict[str, dict[str, Any]] = {}
        self._loaded: set[str] = set()

    def _load(self, prompt_name: str) -> dict[str, Any]:
        """Load a YAML example pool for the given prompt name."""
        if prompt_name in self._loaded:
            return self._pools.get(prompt_name, {})

        filename = _PROMPT_FILE_MAP.get(prompt_name)
        if not filename:
            logger.warning("example_store.no_file_map", prompt=prompt_name)
            self._loaded.add(prompt_name)
            self._pools[prompt_name] = {}
            return {}

        filepath = self._examples_dir / filename
        if not filepath.exists():
            logger.warning("example_store.file_not_found", path=str(filepath))
            self._loaded.add(prompt_name)
            self._pools[prompt_name] = {}
            return {}

        try:
            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._pools[prompt_name] = data
            self._loaded.add(prompt_name)
            logger.info("example_store.loaded", prompt=prompt_name, path=str(filepath))
        except Exception as exc:
            logger.error("example_store.load_failed", prompt=prompt_name, error=str(exc))
            self._pools[prompt_name] = {}

        return self._pools.get(prompt_name, {})

    def select(
        self,
        prompt_name: str,
        context: dict[str, Any] | None = None,
        max_examples: int = 5,
    ) -> str:
        """Select relevant examples for the given prompt and context.

        Strategy:
        1. Load the example pool for the prompt.
        2. Filter examples whose tags overlap with the context tags.
        3. Always include 1 general/base example + 1 negative example.
        4. Fill remaining slots with best-matching examples, ensuring diversity.
        5. Return formatted XML string or empty string if no pool found.

        Args:
            prompt_name: Logical prompt name.
            context: Dict with keys like ``response_type``, ``intent``, ``category``.
            max_examples: Max number of examples to return.

        Returns:
            Formatted XML examples string (empty if no pool or no matches).
        """
        pool = self._load(prompt_name)
        all_examples: list[dict[str, Any]] = pool.get("examples", [])
        if not all_examples:
            return ""

        context = context or {}
        response_type: str | None = context.get("response_type")
        intent_text: str = (context.get("intent") or "").lower()
        context_tags: set[str] = set()
        if response_type:
            context_tags.add(response_type)
            context_tags.add(f"resp:{response_type}")
        for word in intent_text.split():
            if len(word) > 3:
                context_tags.add(word)

        # Score each example by tag overlap
        scored: list[tuple[float, dict[str, Any]]] = []
        for ex in all_examples:
            ex_tags: list[str] = ex.get("tags", [])
            ex_cat: str = ex.get("category", "")
            is_negative = ex_cat.startswith("negative-")

            tag_overlap = len(context_tags & set(ex_tags))
            cat_match = 1.0 if any(context_tags & {ex_cat, f"cat:{ex_cat}"}) else 0.0

            score = float(tag_overlap) + cat_match
            if is_negative:
                score += 0.01  # ensure negatives aren't filtered out entirely
            scored.append((score, ex))

        # Sort by score descending
        scored.sort(key=lambda x: -x[0])

        # Separate out: general, negatives, matched
        general: list[dict[str, Any]] = []
        negatives: list[dict[str, Any]] = []
        matched: list[dict[str, Any]] = []

        for score, ex in scored:
            cat = ex.get("category", "")
            if cat == "general":
                general.append(ex)
            elif cat.startswith("negative-"):
                negatives.append(ex)
            else:
                matched.append(ex)

        selected: list[dict[str, Any]] = []

        # Always include 1 general if available
        if general:
            selected.append(general[0])

        # Always include 1 negative if available
        if negatives:
            selected.append(negatives[0])

        # Fill with best-scoring matched examples
        for ex in matched:
            if len(selected) >= max_examples:
                break
            if ex not in selected:
                selected.append(ex)

        # If still below max, add more negatives or general
        if len(selected) < max_examples:
            for ex in negatives[1:] + general[1:]:
                if len(selected) >= max_examples:
                    break
                if ex not in selected:
                    selected.append(ex)

        # Shuffle slightly to avoid position bias while keeping first 2 stable
        if len(selected) > 2:
            tail = selected[2:]
            random.shuffle(tail)
            selected = selected[:2] + tail

        return _format_examples(selected[:max_examples])

    def get_common_mistakes(
        self,
        prompt_name: str,
        max_mistakes: int = 5,
    ) -> str:
        """Retrieve common mistakes section for the given prompt.

        Args:
            prompt_name: Logical prompt name.
            max_mistakes: Max mistakes to include.

        Returns:
            Formatted XML common_mistakes string (empty if none).
        """
        pool = self._load(prompt_name)
        mistakes: list[dict[str, Any]] = pool.get("common_mistakes", [])
        if not mistakes:
            return ""
        selected = mistakes[:max_mistakes]
        return _format_common_mistakes(selected)

    def list_pools(self) -> list[str]:
        """Return all prompt names that have YAML files."""
        return list(_PROMPT_FILE_MAP.keys())


example_store = ExampleStore()
"""Default singleton ExampleStore instance."""
