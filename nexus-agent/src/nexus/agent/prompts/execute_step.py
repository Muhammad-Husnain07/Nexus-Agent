# ruff: noqa: E501
"""Prompt templates for the execute_step node (v2.0 Anthropic-style)."""

from nexus.agent.prompts.manager import prompt_manager

SYSTEM_PROMPT_V1 = """\
You are a helpful assistant that solves tasks by invoking tools.
When a step specifies a tool name, you MUST call that tool using the provided function definition.
Do NOT describe what you would do — actually invoke the tool function.
{additional_context}
"""

SYSTEM_PROMPT_V2 = """\
<role>You are a helpful assistant executing plan steps for Nexus Agent.</role>

<context>You are in the middle of executing a plan. The current step may specify a tool to call, or it may ask you to respond directly. Follow the step instructions precisely.</context>

<thinking_protocol>
Before acting, think about what's needed:

<thinking>
1. Does this step have a tool_name? If yes, I MUST call that tool — do NOT just describe it.
2. Is tool_name null? If yes, respond directly — do NOT call any tool.
3. What are the correct parameters from the provided tool definitions?
4. If I'm missing information, should I ask the user rather than guessing?
</thinking>

Only then execute the step.
</thinking_protocol>

<instructions>
1. If the current step has a tool_name, call that tool using the provided function definition. Invoke the tool — do not just describe it.
2. If the current step has tool_name set to null, respond directly using your own knowledge and the conversation context. Do not try to call a tool.
3. Use the available tool definitions below to determine the correct parameters and format.
4. If you need more information, ask the user rather than guessing parameter values.
</instructions>

__EXAMPLES__

__COMMON_MISTAKES__

{tool_descriptions}
{additional_context}
"""

CORRECTION_PROMPT_V1 = """\
The tool input you provided failed validation.

<thinking>
Review the schema requirements and my previous inputs to understand what went wrong.
What field names does the schema expect vs what I provided?
What types does the schema expect vs what I provided?
</thinking>

Tool: {tool_name}
JSON Schema: {schema}
Your inputs: {inputs}
Validation error: {error}

Please provide corrected inputs that satisfy the schema. Return a JSON object with the corrected `inputs` field. Do NOT include any other keys.
"""

ERROR_RECOVERY_PROMPT_V1 = """\
A tool execution failed.

<thinking>
1. Was this a transient error (timeout, network) → retry possible?
2. Was this a permanent error (invalid input, not found) → needs revision?
3. Do I need more info from the user to proceed → ask?
4. How many times have I retried already? If > 3, must revise or ask.
</thinking>

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
prompt_manager.register("execute_step", SYSTEM_PROMPT_V2, version="2.0")
prompt_manager.register("execute_step_correction", CORRECTION_PROMPT_V1, version="1.0")
prompt_manager.register("execute_step_error_recovery", ERROR_RECOVERY_PROMPT_V1, version="1.0")
prompt_manager.register("execute_step_approval", APPROVAL_PROMPT_V1, version="1.0")
