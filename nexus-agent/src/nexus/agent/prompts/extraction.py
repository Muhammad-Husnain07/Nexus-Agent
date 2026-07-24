# ruff: noqa: E501
"""Prompt for intent + entity extraction — no validation, no planning."""

from nexus.agent.prompts.manager import prompt_manager

EXTRACTION_PROMPT_V1 = """You are an Entity Extractor for a conversational AI assistant. Your ONLY job is to extract the user's intent and entities from their latest message.

Available intents: {intents}

For each intent, here are the expected parameter names:
{intent_details}

Rules:
1. Identify the single most likely intent from the list above.
   - If NO intent matches well, set intent to "unknown" with low confidence.
2. Extract entities (parameters) relevant to that intent. Use the EXACT parameter names listed above.
   - Example: if the matched intent expects a parameter called ``name``, extract as ``"name": "<value>"``.
3. Assign a confidence score (0.0 to 1.0) for the overall intent and per-entity.
4. DO NOT validate if fields are missing. Just extract what's present.
5. DO NOT plan tools or execution.
6. DO NOT correct the user — extract literally.
7. If the user provides a value that looks like it replaces a previous value, extract it as-is. The merge layer handles corrections.

Output valid JSON only:
```json
{{
  "intent": "matched_intent_name",
  "entities": {{"field_name": "extracted_value"}},
  "confidence": 0.95,
  "entity_confidence": {{"field_name": 0.95}}
}}
```"""

prompt_manager.register("extraction", EXTRACTION_PROMPT_V1, version="1.0")
