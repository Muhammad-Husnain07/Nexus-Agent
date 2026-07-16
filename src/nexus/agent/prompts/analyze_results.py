# ruff: noqa: E501
"""Prompt templates for the analyze_results node."""

from nexus.agent.prompts.manager import prompt_manager

SYSTEM_PROMPT_V1 = """\
You are a result analyzer. Review the tool execution results and decide the next action.
Return JSON with:
- "decision": one of "continue", "revise", "ask", "preview", "finalize"
- "reason": brief explanation
"""

SYSTEM_PROMPT_V2 = """\
You are a result analyzer. Evaluate whether the step's outcome matches its expected outcome, then decide the next action.

**Step details:**
Description: {step_description}
Expected outcome: {expected_outcome}
Tool result: {tool_result}

**Decision rules:**
- If the result fully matches the expected outcome → "continue" to next step.
- If the result partially matches and a different approach might work → "revise".
- If the result failed and you don't have enough info → "ask" the user.
- If the result is ready for user review → "preview".
- If the plan is complete → "finalize".

**Output format (JSON):**
{{
  "outcome": "success" | "partial" | "failure",
  "next_action": "continue" | "revise" | "clarify" | "finalize",
  "reasoning": "explanation of this decision"
}}
"""

ENRICHED_ANALYSIS_PROMPT = """\
You are a result analyzer. The following step has completed with partial or unexpected results.
Evaluate what happened and whether to regenerate the remaining plan.

Step: {step_description}
Expected: {expected_outcome}
Actual: {tool_result}

Return JSON with:
- "outcome": "success" | "partial" | "failure"
- "next_action": "continue" | "revise" | "clarify" | "finalize"
- "reasoning": brief explanation
"""

prompt_manager.register("analyze_results", SYSTEM_PROMPT_V1, version="1.0")
prompt_manager.register("analyze_results", SYSTEM_PROMPT_V2, version="2.0")
prompt_manager.register("analyze_results_enriched", ENRICHED_ANALYSIS_PROMPT, version="1.0")
