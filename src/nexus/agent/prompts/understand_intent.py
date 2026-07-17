# ruff: noqa: E501
"""Prompt templates for the understand_intent node."""

from nexus.agent.prompts.manager import prompt_manager

SYSTEM_PROMPT_V1 = """\
You are an intent parser. Given a user message, extract the structured intent.
Return JSON with:
- "intent": a short verb-noun phrase describing the goal
- "parameters": dict of extracted parameters (empty dict if none)
- "missing_info_slots": list of required info not provided (empty list if all present)
"""

SYSTEM_PROMPT_V2 = """\
You are an intent analysis system. Given a user message and the current conversation context, produce a structured analysis.

**Rules:**
1. Extract the **primary goal** — what the user ultimately wants to achieve.
2. List any **implied actions** that are needed but not explicitly stated.
3. Identify **missing information slots** — any required info the user has NOT yet provided.
4. Extract **known_parameters** — parameter values the user has ALREADY provided in their message.
5. Rate **confidence** (0-1) in your analysis.
6. Rate **urgency** (low/normal/high) based on explicit cues.
7. Distinguish between "I want X" (a goal to plan for) and "do X now" (an actionable command).
8. If the user says e.g. "Tech category", the value "Tech" is ALREADY known — put it in known_parameters, NOT in missing_info_slots.
9. Use these exact categories: Tech, Science, Sports, News.

**Few-shot examples:**
{examples}

**Output format (JSON):**\
"""

FEW_SHOT_EXAMPLES = """\
Example 1:
User: "send an email to john@example.com saying the meeting is at 3pm"
Analysis:
{
  "primary_goal": "send email to recipient",
  "implied_actions": ["compose email body", "send via email tool"],
  "known_parameters": {"recipient": "john@example.com"},
  "missing_info_slots": [
    {
      "name": "email_body",
      "description": "The content of the email",
      "why_needed": "required by send_email tool",
      "suggested_question": "What would you like the email to say?",
      "possible_values": null,
      "source": "user"
    }
  ],
  "confidence": 0.95,
  "urgency": "normal"
}

Example 2:
User: "what's the weather in London?"
Analysis:
{
  "primary_goal": "check weather forecast",
  "implied_actions": ["query weather API"],
  "known_parameters": {"location": "London"},
  "missing_info_slots": [],
  "confidence": 0.98,
  "urgency": "normal"
}

Example 3:
User: "delete all production databases"
Analysis:
{
  "primary_goal": "delete production databases",
  "implied_actions": ["list databases", "execute drop commands"],
  "known_parameters": {},
  "missing_info_slots": [],
  "confidence": 0.99,
  "urgency": "high"
}

Example 4:
User: "list articles in the Tech category"
Analysis:
{
  "primary_goal": "list articles",
  "implied_actions": ["query articles API"],
  "known_parameters": {"category": "Tech"},
  "missing_info_slots": [],
  "confidence": 0.97,
  "urgency": "normal"
}

Example 5:
User: "show me articles"
Analysis:
{
  "primary_goal": "list articles",
  "implied_actions": ["query articles API"],
  "known_parameters": {},
  "missing_info_slots": [
    {
      "name": "category",
      "description": "Article category to filter by",
      "why_needed": "category narrows down the results",
      "suggested_question": "What category of articles are you looking for?",
      "possible_values": ["Tech", "Science", "Sports", "News"],
      "source": "user"
    }
  ],
  "confidence": 0.92,
  "urgency": "normal"
}

Example 6:
User: "list all tags"
Analysis:
{
  "primary_goal": "list tags",
  "implied_actions": ["query tags API"],
  "known_parameters": {},
  "missing_info_slots": [],
  "confidence": 0.99,
  "urgency": "normal"
}
"""

prompt_manager.register("understand_intent", SYSTEM_PROMPT_V1, version="1.0")
prompt_manager.register(
    "understand_intent",
    SYSTEM_PROMPT_V2,
    version="2.0",
    metadata={"few_shot": FEW_SHOT_EXAMPLES},
)
