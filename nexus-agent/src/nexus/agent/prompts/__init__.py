"""Prompt templates for agent nodes — loaded by PromptManager."""

import nexus.agent.prompts.finalize  # noqa: F401
from nexus.agent.prompts.manager import PromptManager, PromptTemplate, prompt_manager

__all__ = [
    "PromptManager",
    "PromptTemplate",
    "prompt_manager",
]
