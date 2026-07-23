"""PromptAdapter — adapts prompts between formats with zero hardcoded model names.

Usage::

    adapter = PromptAdapter()
    adapter.set_format("openai")
    adapted = adapter.adapt(
        system="<role>You are...</role>",
        messages=[{"role": "user", "content": "Hello"}],
    )
"""

from __future__ import annotations

from typing import Any

import structlog

from nexus.llm.format_adapter.transformers import (
    FORMAT_TRANSFORMERS,
    _BaseTransformer,
    get_transformer,
)

log = structlog.get_logger(__name__)


class PromptAdapter:
    """Configuration-driven prompt format adapter.

    Transforms prompts from internal XML format to the target model's
    expected format, based on the configured or probe-detected format name.
    """

    def __init__(self, format_name: str | None = None) -> None:
        self._transformer: _BaseTransformer | None = None
        if format_name:
            self.set_format(format_name)

    def set_format(self, format_name: str) -> None:
        """Switch to a different format transformer."""
        self._transformer = get_transformer(format_name)
        log.info("format_adapter.switched", format=format_name)

    @property
    def active_format(self) -> str | None:
        if self._transformer is None:
            return None
        for name, tf in FORMAT_TRANSFORMERS.items():
            if tf is self._transformer:
                return name
        return None

    def adapt(
        self,
        system: str | None = None,
        messages: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Adapt messages to the currently set format.

        Args:
            system: System prompt in internal XML format.
            messages: Message history in internal format.

        Returns:
            Messages adapted to the target format.
        """
        transformer = self._transformer
        if transformer is None:
            return messages or []

        adapted = list(messages or [])
        if system:
            # Remove original system message if present (it will be replaced)
            if adapted and adapted[0].get("role") == "system":
                adapted = adapted[1:]
            adapted = transformer.wrap_messages(
                transformer.transform_system(system), adapted
            )
        return adapted
