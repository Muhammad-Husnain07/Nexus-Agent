# ruff: noqa: E501
"""Prompt templates for the finalize node."""

from nexus.agent.prompts.manager import prompt_manager

SYSTEM_PROMPT_V1 = """\
Summarize the following tool execution results for the user.
Be concise and highlight what was accomplished.
Results: {summary}
"""

SYSTEM_PROMPT_V2 = """\
You are a helpful assistant wrapping up a task. Compose a final response that:

1. Briefly states what was done and whether it succeeded.
2. Lists the tools that were called with key results.
3. Highlights any important information the user should know.
4. If errors occurred, explains them clearly.
5. If nothing was done, explains why.

**Tool results:**
{tool_citations}

**Errors (if any):**
{errors_summary}

Be concise and natural. Use bullet points for clarity where appropriate.
"""

prompt_manager.register("finalize", SYSTEM_PROMPT_V1, version="1.0")
prompt_manager.register("finalize", SYSTEM_PROMPT_V2, version="2.0")
