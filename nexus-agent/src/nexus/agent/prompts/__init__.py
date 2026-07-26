"""Prompt templates for agent nodes — loaded by PromptManager.

Only 3 prompts remain in the strict 3-prompt architecture:
1. ``finalize`` — Response Narrative (kept)
2. ``logical_planner`` — Semantic Workflow Translator (new)
3. ``router`` — Query classifier (planned)
"""

import nexus.agent.prompts.finalize  # noqa: F401
import nexus.agent.prompts.logical_planner  # noqa: F401
import nexus.agent.prompts.router  # noqa: F401
from nexus.agent.prompts.manager import PromptManager, PromptTemplate, prompt_manager

__all__ = [
    "PromptManager",
    "PromptTemplate",
    "prompt_manager",
]
