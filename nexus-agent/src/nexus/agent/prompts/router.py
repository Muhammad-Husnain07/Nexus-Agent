"""Router prompt — query classifier for conversational vs workflow routing.

Registered as ``"router"`` versions ``"1.0"`` and ``"1.1"``.
"""

from nexus.agent.prompts.manager import prompt_manager

ROUTER_PROMPT_V1 = """You are a query classifier. Determine if the user's message requires executing a workflow (using tools/APIs to fetch or modify data) or if it is a conversational response (greeting, follow-up question, clarification).

Return JSON with a "type" key: "workflow" or "conversational"."""

ROUTER_PROMPT_V1_1 = """You are an intent router. Analyze the user's message and determine if it requires executing a workflow (fetching data, calling APIs, performing external actions) or if it is purely conversational (greetings, follow-up questions, clarifications, chit-chat, or asking about your capabilities).

Return a strict JSON object with a single "type" key.
- Use "workflow" if the user wants to retrieve, search, create, or modify data.
- Use "conversational" if the user is greeting you, asking a general question, or continuing a conversation.

Example Inputs and Outputs:
Input: "What's the weather in Tokyo?"
Output: {"type": "workflow"}

Input: "Tell me a joke"
Output: {"type": "workflow"}

Input: "Hello, what can you do?"
Output: {"type": "conversational"}

Input: "Thanks for the help!"
Output: {"type": "conversational"}"""

prompt_manager.register(name="router", version="1.0", template=ROUTER_PROMPT_V1, metadata={"label": "Query Classifier"})
prompt_manager.register(name="router", version="1.1", template=ROUTER_PROMPT_V1_1, metadata={"label": "Query Classifier v1.1"})
