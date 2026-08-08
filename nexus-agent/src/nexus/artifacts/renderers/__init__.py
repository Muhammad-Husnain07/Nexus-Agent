"""Artifact renderers — transform typed artifacts into LLM-readable text blocks.

Each capability can have a custom renderer registered via the RendererRegistry.
Renderers are sandboxed by the PromptRenderer (asyncio.wait_for 2s timeout).
"""
