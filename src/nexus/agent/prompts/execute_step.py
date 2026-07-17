# ruff: noqa: E501
"""Prompt templates for the execute_step node."""

from nexus.agent.prompts.manager import prompt_manager

SYSTEM_PROMPT_V1 = """\
You are a helpful assistant that solves tasks by invoking tools.
When a step specifies a tool name, you MUST call that tool using the provided function definition.
Do NOT describe what you would do — actually invoke the tool function.
{additional_context}
"""

CORRECTION_PROMPT_V1 = """\
The tool input you provided failed validation.

Tool: {tool_name}
JSON Schema: {schema}
Your inputs: {inputs}
Validation error: {error}

Please provide corrected inputs that satisfy the schema. Return a JSON object with the corrected `inputs` field. Do NOT include any other keys.
"""

ERROR_RECOVERY_PROMPT_V1 = """\
A tool execution failed.

Step: {step_description}
Tool: {tool_name}
Error: {error}
Previous results: {previous_results}

Decide what to do next. Return JSON:
- "action": "retry" | "revise" | "ask"
  - "retry": the same tool call with the same or modified inputs
  - "revise": the plan needs to change (step is fundamentally wrong)
  - "ask": not enough information, ask the user
- "reasoning": brief explanation
- "modified_inputs": (only if action=="retry") the corrected inputs
"""

APPROVAL_PROMPT_V1 = """\
A tool requires human approval before execution.

Tool: {tool_name}
Step description: {step_description}
Inputs: {inputs}
Risk level: {risk_level}

Set `pending_approval` and yield an approval_required event.
"""

prompt_manager.register("execute_step", SYSTEM_PROMPT_V1, version="1.0")
prompt_manager.register("execute_step_correction", CORRECTION_PROMPT_V1, version="1.0")
prompt_manager.register("execute_step_error_recovery", ERROR_RECOVERY_PROMPT_V1, version="1.0")
prompt_manager.register("execute_step_approval", APPROVAL_PROMPT_V1, version="1.0")
