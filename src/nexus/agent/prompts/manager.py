"""PromptManager — central prompt registry with versioning and A/B testing.

Usage::

    from nexus.agent.prompts import prompt_manager

    prompt = prompt_manager.render("understand_intent", version="2.0", goal="send email")
"""

from __future__ import annotations

import secrets
from typing import Any

from pydantic import BaseModel, Field


class PromptTemplate(BaseModel):
    """A registered prompt template with versioning metadata.

    Attributes:
        name: Logical name shared across versions (e.g. ``"understand_intent"``).
        version: Semantic version string (e.g. ``"1.0"``, ``"2.0"``).
        template: The prompt text with ``{placeholders}`` for ``str.format``.
        metadata: Arbitrary metadata (e.g. ``{"few_shot": "...", "author": "..."}``).
    """

    name: str = Field(description="Logical prompt name")
    version: str = Field(description="Semantic version string")
    template: str = Field(description="Prompt text with {placeholders}")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")


class PromptManager:
    """Registry of prompt templates with versioning and A/B selection.

    The manager stores templates by ``(name, version)``.  When no version is
    requested, the highest registered version is returned.  A/B testing can
    be enabled per prompt name via ``ab_test_weights``.
    """

    def __init__(self, ab_test_weights: dict[str, dict[str, float]] | None = None) -> None:
        self._templates: dict[str, dict[str, PromptTemplate]] = {}
        self._ab_test_weights: dict[str, dict[str, float]] = ab_test_weights or {}

    def register(
        self,
        name: str,
        template: str,
        version: str = "1.0",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a prompt template.

        Args:
            name: Logical name (e.g. ``"understand_intent"``).
            template: Prompt text with ``{placeholders}``.
            version: Semantic version (e.g. ``"1.0"``).
            metadata: Optional metadata dict.
        """
        if name not in self._templates:
            self._templates[name] = {}
        self._templates[name][version] = PromptTemplate(
            name=name, version=version, template=template, metadata=metadata or {}
        )

    def get(self, name: str, version: str | None = None) -> PromptTemplate:
        """Retrieve a prompt template by name and optional version.

        Args:
            name: Logical prompt name.
            version: Desired version.  If None, applies A/B weights or returns
                the highest registered version.

        Returns:
            The matching ``PromptTemplate``.

        Raises:
            KeyError: If the name is not registered or the version doesn't exist.
        """
        versions = self._templates.get(name)
        if versions is None:
            raise KeyError(f"Unknown prompt: '{name}'")

        if version is not None:
            tmpl = versions.get(version)
            if tmpl is None:
                raise KeyError(f"Unknown version '{version}' for prompt '{name}'")
            return tmpl

        # A/B testing — pick version based on configured weights
        weights = self._ab_test_weights.get(name)
        if weights:
            candidates = list(weights.keys())
            probs = list(weights.values())
            selected = secrets.SystemRandom().choices(candidates, weights=probs, k=1)[0]
            tmpl = versions.get(selected)
            if tmpl is not None:
                return tmpl

        # Fallback to highest version
        sorted_versions = sorted(versions.keys(), key=lambda v: [int(x) for x in v.split(".")])
        return versions[sorted_versions[-1]]

    def render(self, prompt_name: str, prompt_version: str | None = None, **kwargs: Any) -> str:
        """Retrieve and format a prompt template.

        Args:
            name: Logical prompt name.
            version: Desired version (see :meth:`get`).
            **kwargs: Format arguments for the template.

        Returns:
            The formatted prompt string.
        """
        tmpl = self.get(prompt_name, version=prompt_version)
        return tmpl.template.format(**kwargs)

    def list_versions(self, name: str) -> list[str]:
        """Return all registered version strings for a prompt name."""
        versions = self._templates.get(name, {})
        return sorted(versions.keys(), key=lambda v: [int(x) for x in v.split(".")])


prompt_manager = PromptManager()
"""Default singleton PromptManager instance."""
