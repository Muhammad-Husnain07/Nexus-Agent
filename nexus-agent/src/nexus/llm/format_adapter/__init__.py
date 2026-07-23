"""Prompt format adaptation — transforms prompts between formats.

Converts internal XML-style prompts to the target model's format
based on the detected or configured format. Zero hardcoded model names.
"""
from nexus.llm.format_adapter.adapter import PromptAdapter, get_transformer

__all__ = ["PromptAdapter", "get_transformer"]
