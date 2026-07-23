# ruff: noqa: E501
"""Prompt templates for the understand_intent node — dynamic depth based on query complexity."""

from nexus.agent.prompts.manager import prompt_manager

SYSTEM_PROMPT_V1 = """\
You are an intent parser. Given a user message, extract the structured intent.
Return JSON with:
- "intent": a short verb-noun phrase describing the goal
- "parameters": dict of extracted parameters (empty dict if none)
- "missing_info_slots": list of required info not provided (empty list if all present)
"""

# ── Base instructions (shared between simple and complex paths) ─────────
_BASE = """\
<role>You are Nexus Agent, an intent analysis system. Analyze what the user wants and how to respond.</role>

<context>Your classification decides whether to invoke tools or respond directly.</context>

<instructions>
1. Extract primary_goal — short verb-noun phrase.
2. List implied_actions — actions implied but not stated.
3. Identify missing_info_slots — required info not yet provided.
4. Extract known_parameters — values already given.
5. Rate confidence 0-1 based on clarity.
6. Rate urgency: low | normal | high.
7. Decide needs_tool: true for data/actions/API calls, false for greetings/meta/memory.
8. Set response_type: tool | greeting | meta | memory_query.
9. Use conversation history to resolve pronouns.
10. Output ONLY valid JSON matching the output_format below. No preamble, no explanation.
</instructions>

<rules>
<rule context="known_parameters">If the user says e.g. "Tech category", put "Tech" in known_parameters, NOT in missing_info_slots.</rule>
<rule context="conversation_context">Use history to resolve pronouns like "it", "that", "another", "more".</rule>
<rule context="corrections_and_followups">If the user's message follows a failed/incomplete attempt, treat it as fulfilling the ORIGINAL intent — keep needs_tool true if the original needed it.</rule>
<rule context="followup_questions">Short follow-ups like "Why?", "How?", "Tell me more" refer back to the previous exchange — continue the original thread.</rule>
<rule context="needs_tool">needs_tool=true for factual data, info retrieval, content generation (jokes, facts, trivia, images), real-time data (weather, prices), actions. false ONLY for greetings, social chat, questions about the agent, or past memories.</rule>
</rules>"""

# ── Short thinking block (added for medium complexity) ──────────────────
_SHORT_THINKING = """\
<thinking>
1. What response_type fits? If the query has multiple distinct requests joined by "and"/"also", treat each independently but produce ONE analysis covering all.
2. Which parameters are already provided? Which are missing?
</thinking>"""

# ── Full thinking block (added for complex queries) ────────────────────
_FULL_THINKING = """\
<thinking>
1. What is the user's primary goal? Capture ALL distinct requests — compound queries may have multiple intents.
2. For each request: what data/action is needed? Which known_parameters are provided? Which are missing?
3. What response_type fits each request? If ANY request needs a tool, set needs_tool=true.
4. Rate confidence: clear request = high, vague/ambiguous = low.
5. Is this a follow-up to a previous turn? Check pronouns and implicit references.
</thinking>"""

SYSTEM_PROMPT_COMPLEX = _BASE + "\n" + _FULL_THINKING + """
__EXAMPLES__
__COMMON_MISTAKES__

Wrap your JSON output inside <output> tags.

<output_format>
{{"primary_goal": "verb-noun phrase", "implied_actions": [...], "known_parameters": {{}}, "missing_info_slots": [...], "confidence": 0.0-1.0, "urgency": "low"|"normal"|"high", "needs_tool": true|false, "response_type": "tool"|"greeting"|"meta"|"memory_query"}}
</output_format>\
"""

SYSTEM_PROMPT_SIMPLE = _BASE + """
Wrap your JSON output inside <output> tags.

<output_format>
{{"primary_goal": "verb-noun phrase", "implied_actions": [...], "known_parameters": {{}}, "missing_info_slots": [...], "confidence": 0.0-1.0, "urgency": "low"|"normal"|"high", "needs_tool": true|false, "response_type": "tool"|"greeting"|"meta"|"memory_query"}}
</output_format>\
"""

prompt_manager.register("understand_intent", SYSTEM_PROMPT_V1, version="1.0")
prompt_manager.register("understand_intent", SYSTEM_PROMPT_SIMPLE, version="4.0-simple")
prompt_manager.register("understand_intent", SYSTEM_PROMPT_COMPLEX, version="4.0-complex")
