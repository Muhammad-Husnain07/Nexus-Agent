"""RendererRegistry — discovers and manages artifact renderers.

Includes source-code checksum in the version hash so that code changes
invalidate the prompt cache automatically.  Uses ``GenericRenderer``
as the default fallback for any capability without a registered renderer.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import logging
import pkgutil
import threading
from typing import Any

from nexus.artifacts.renderers.base import ArtifactRenderer
from nexus.artifacts.renderers.generic import GenericRenderer

logger = logging.getLogger(__name__)


class RendererRegistry:
    """Thread-safe registry of artifact renderers keyed by capability_id."""

    _renderers: dict[str, Any] = {}
    _default = GenericRenderer()
    _initialized: bool = False
    _lock = threading.Lock()

    @classmethod
    def register(cls, capability_id: str, renderer: ArtifactRenderer) -> None:
        """Register a renderer for a capability."""
        cls._renderers[capability_id] = renderer

    @classmethod
    def get_renderer(cls, capability_id: str) -> ArtifactRenderer:
        """Get the renderer for a capability, or the ``GenericRenderer`` default."""
        return cls._renderers.get(capability_id, cls._default)

    @classmethod
    def get(cls, capability_id: str) -> ArtifactRenderer:
        """Compatibility alias for ``get_renderer`` (the response renderer
        path calls ``get`` — previously missing, silently degrading every
        artifact to the raw-JSON preview)."""
        return cls.get_renderer(capability_id)

    @classmethod
    def version_hash(cls) -> str:
        """Compute a version hash that includes renderer source checksums
        AND the architecture fingerprint (ADR 0008) — any code change to a
        renderer or any architecture bump invalidates cached prompts."""
        h = hashlib.sha256()
        for cap, rend in sorted(cls._renderers.items()):
            try:
                source = inspect.getsource(rend.__class__)
            except Exception:
                source = ""
            h.update(f"{cap}:{rend.__class__.__name__}:{hashlib.sha256(source.encode()).hexdigest()}".encode())
        try:
            from nexus.agent.architecture import ArchitectureVersion

            h.update(ArchitectureVersion.cache_fingerprint().encode())
        except Exception:
            pass
        return h.hexdigest()[:8]

    @classmethod
    def initialize(cls, package_path: str = "nexus.artifacts.renderers") -> None:
        """Auto-discover renderers via pkgutil.iter_modules."""
        with cls._lock:
            if cls._initialized:
                return
            try:
                pkg = importlib.import_module(package_path)
                for _finder, module_name, _ispkg in pkgutil.iter_modules(pkg.__path__):
                    importlib.import_module(f"{package_path}.{module_name}")
                cls._initialized = True
            except Exception as e:
                logger.warning("Renderer discovery failed: %s", e)
