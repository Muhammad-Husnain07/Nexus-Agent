"""Prompt templates for agent nodes — loaded by PromptManager."""

# Import to trigger registration
import nexus.agent.prompts.analyze_results  # noqa: F401
import nexus.agent.prompts.execute_step  # noqa: F401
import nexus.agent.prompts.finalize  # noqa: F401
import nexus.agent.prompts.gather_requirements  # noqa: F401
import nexus.agent.prompts.plan  # noqa: F401
import nexus.agent.prompts.understand_intent  # noqa: F401
from nexus.agent.prompts.manager import PromptManager, PromptTemplate, prompt_manager

__all__ = [
    "PromptManager",
    "PromptTemplate",
    "prompt_manager",
]
