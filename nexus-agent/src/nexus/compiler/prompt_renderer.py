"""PromptRenderer — sandboxed rendering of ContextIR into LLM messages.

Each artifact renderer is executed with ``asyncio.wait_for(timeout=2.0)``
to prevent infinite loops.  The renderer computes actual diagnostics from
the rendered message content — not mocked values.
"""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from nexus.compiler.context_ir import ContextIR, ContextSection

logger = logging.getLogger(__name__)


@dataclass
class ModelProfile:
    """Profile of the target model's capabilities."""
    supports_system: bool = True


@dataclass
class PromptValidationReport:
    """Diagnostic report from rendering a compiled ContextIR."""
    is_valid: bool
    total_tokens: int
    budget: int
    overflow: int
    diagnostics: dict[str, int]


class PromptRenderer:
    """Renders a ContextIR into LLM messages with sandboxed artifact renderers.

    Each artifact renderer call is timeout-guarded (2s) and fallback-safe.
    """

    def __init__(self) -> None:
        self._renderers: dict[str, Any] = {}

    def register_renderer(self, capability_id: str, renderer: Any) -> None:
        """Register a renderer for a specific capability."""
        self._renderers[capability_id] = renderer

    def render_mock(self, ir: ContextIR) -> list[dict[str, Any]]:
        """Lightweight render for token estimation (no sandbox)."""
        messages: list[dict[str, Any]] = []
        context_blocks: list[str] = []
        query_content = ""

        for item in ir.items:
            if item.section == ContextSection.SYSTEM_INSTRUCTIONS and item.content:
                messages.append({"role": "system", "content": item.content})
            elif item.section == ContextSection.USER_INTENT and item.content:
                query_content = item.content
            elif item.section == ContextSection.ARTIFACTS and item.projection:
                data_str = str(item.projection.data)[:2000]
                context_blocks.append(f"[{item.projection.artifact_type}] {data_str}")
            elif item.section == ContextSection.HISTORY and item.content:
                messages.append({"role": item.speaker, "content": item.content})

        final_content = query_content
        if context_blocks:
            final_content += "\n\n### Context:\n" + "\n\n".join(context_blocks)
        messages.append({"role": "user", "content": final_content})
        return messages

    async def render(
        self,
        ir: ContextIR,
        profile: ModelProfile,
        model: str,
        cancellation_token: asyncio.Event | None = None,
    ) -> tuple[list[dict[str, Any]], PromptValidationReport]:
        """Render the ContextIR into LLM messages with sandboxed artifact renderers.

        Each artifact renderer is called via ``asyncio.to_thread`` with a
        2-second timeout.  Falls back to a generic string representation
        on failure.
        """
        messages: list[dict[str, Any]] = []
        context_blocks: list[str] = []
        query_content = ""

        for item in ir.items:
            if cancellation_token and cancellation_token.is_set():
                raise asyncio.CancelledError("Renderer cancelled")

            if item.section == ContextSection.SYSTEM_INSTRUCTIONS:
                if item.content:
                    if profile.supports_system:
                        messages.append({"role": "system", "content": item.content})
                    else:
                        context_blocks.append(f"Instructions:\n{item.content}")

            elif item.section == ContextSection.USER_INTENT:
                if item.content:
                    query_content = item.content

            elif item.section == ContextSection.ARTIFACTS and item.projection:
                renderer = self._renderers.get(item.projection.capability_id)
                if renderer and hasattr(renderer, "render"):
                    try:
                        safe_payload = deepcopy(item.projection.data)
                        # Convert to standard dict in case data contains MappingProxyType
                        if hasattr(safe_payload, "keys"):
                            safe_payload = {k: v for k, v in safe_payload.items()}
                        rendered = await asyncio.wait_for(
                            asyncio.to_thread(renderer.render, safe_payload),
                            timeout=2.0,
                        )
                        if len(rendered) > 10000:
                            rendered = rendered[:10000] + "... [Renderer output truncated]"
                    except asyncio.TimeoutError:
                        logger.error("Renderer %s timed out. Falling back.", renderer.__class__.__name__)
                        rendered = f"[{item.projection.artifact_type}] {str(item.projection.data)[:500]}"
                    except Exception as e:
                        logger.error("Renderer %s failed: %s. Falling back.", renderer.__class__.__name__, e)
                        rendered = f"[{item.projection.artifact_type}] {str(item.projection.data)[:500]}"
                else:
                    rendered = f"[{item.projection.artifact_type}] {str(item.projection.data)[:500]}"
                context_blocks.append(rendered)

            elif item.section == ContextSection.HISTORY:
                if item.content:
                    messages.append({"role": item.speaker, "content": item.content})

        # Build final user message with context blocks
        final_user_content = query_content
        if context_blocks:
            final_user_content += "\n\n### Context:\n" + "\n\n".join(context_blocks)
        messages.append({"role": "user", "content": final_user_content})

        # Compute diagnostics
        diag: dict[str, int] = {
            "system": sum(len(m.get("content", "")) // 4 for m in messages if m.get("role") == "system"),
            "history": sum(
                len(m.get("content", "")) // 4
                for m in messages
                if m.get("role") not in ("user", "system")
            ),
            "artifacts": sum(len(b) // 4 for b in context_blocks),
            "user": len(query_content) // 4,
        }
        total_tokens = sum(diag.values())
        report = PromptValidationReport(
            is_valid=total_tokens <= ir.budget_limit,
            total_tokens=total_tokens,
            budget=ir.budget_limit,
            overflow=max(0, total_tokens - ir.budget_limit),
            diagnostics=diag,
        )
        return messages, report
