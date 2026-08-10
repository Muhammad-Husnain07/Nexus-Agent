"""PromptManager — central prompt registry with versioning and A/B testing.

Usage::

    from nexus.agent.prompts import prompt_manager

    prompt = prompt_manager.render("logical_planner", "2.4", capabilities="...", history="...")
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger("nexus.agent.prompts.manager")


class PromptVersionError(KeyError):
    """Raised when a prompt name/version is requested but not registered.

    Fail-closed contract (invariant I9): a missing production prompt is a
    typed configuration error, never a silent quality degradation. Callers
    must not catch this and substitute an ad-hoc prompt.
    """


class PromptTemplate(BaseModel):
    """A registered prompt template with versioning metadata.

    Attributes:
        name: Logical name shared across versions.
        version: Semantic version string (e.g. ``"1.0"``, ``"2.0"``).
        template: The prompt text with ``{placeholders}`` for ``str.format``.
        metadata: Arbitrary metadata.
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
            PromptVersionError: If the name is not registered or the version
                doesn't exist.
        """
        versions = self._templates.get(name)
        if versions is None:
            raise PromptVersionError(f"Unknown prompt: '{name}'")

        if version is not None:
            tmpl = versions.get(version)
            if tmpl is None:
                raise PromptVersionError(f"Unknown version '{version}' for prompt '{name}'")
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

    def render(
        self,
        prompt_name: str,
        prompt_version: str | None = None,
        version: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Retrieve and format a prompt template.

        Uses Python's ``.format()`` which only processes the template string.
        Literal braces in the template must be escaped as ``{{...}}``.

        Args:
            name: Logical prompt name.
            prompt_version: Desired version (see :meth:`get`).
            version: Alias for ``prompt_version`` (accepted as keyword arg
                for backward compatibility).
            **kwargs: Format arguments for the template.

        Returns:
            The formatted prompt string.
        """
        ver = prompt_version or version
        tmpl = self.get(prompt_name, version=ver)
        logger.info("prompt.version_served", prompt=prompt_name, version=tmpl.version)
        return tmpl.template.format(**kwargs)

    def render_with_examples(
        self,
        prompt_name: str,
        context: dict[str, Any] | None = None,
        prompt_version: str | None = None,
        version: str | None = None,
        max_examples: int = 5,
        max_mistakes: int = 5,
        **kwargs: Any,
    ) -> str:
        """Retrieve and format a prompt template (backward compat — same as :meth:`render`).

        Merges ``context`` dict items into ``kwargs`` so they are available
        for template variable substitution.
        """
        if context:
            for k, v in context.items():
                if k not in kwargs:
                    if isinstance(v, (dict, list)):
                        kwargs[k] = json.dumps(v)
                    elif v is not None:
                        kwargs[k] = str(v)
        rendered = self.render(
            prompt_name,
            prompt_version=prompt_version or version,
            **kwargs,
        )
        # Replace any remaining placeholder tags with empty string
        rendered = rendered.replace("__EXAMPLES__", "").replace("__COMMON_MISTAKES__", "")
        return rendered

    def list_versions(self, name: str) -> list[str]:
        """Return all registered version strings for a prompt name."""
        versions = self._templates.get(name, {})
        return sorted(versions.keys(), key=lambda v: [int(x) for x in v.split(".")])

    def fingerprint(self, name: str, version: str | None = None) -> str:
        """P1-B.2: content hash of the registered template (current or the
        given version). A prompt CONTENT change produces a new fingerprint
        even when the version label is unchanged."""
        import hashlib as _hl

        tmpl = self.get(name, version=version)
        return _hl.sha256(tmpl.template.encode()).hexdigest()[:16]

    def fingerprints(self) -> dict[str, str]:
        """P1-B.2: content fingerprints of every registered prompt, keyed
        by prompt name (the highest registered version)."""
        out: dict[str, str] = {}
        for name in self._templates:
            out[name] = self.fingerprint(name)
        return out


prompt_manager = PromptManager()
"""Default singleton PromptManager instance."""
