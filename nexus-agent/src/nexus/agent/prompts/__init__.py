"""Prompt templates for agent nodes — loaded by PromptManager."""

# Import to trigger registration — only active graph prompts
import nexus.agent.prompts.finalize  # noqa: F401
import nexus.agent.prompts.plan_parallel  # noqa: F401
from nexus.agent.prompts.example_store import ExampleStore, example_store
from nexus.agent.prompts.manager import PromptManager, PromptTemplate, prompt_manager

__all__ = [
    "ExampleStore",
    "PromptManager",
    "PromptTemplate",
    "example_store",
    "prompt_manager",
]
