"""Test gemma3:4B tool calling directly."""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "nexus-agent", "src"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "nexus-agent"))

import litellm

async def test():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "cat_fact",
                "description": "Get a random cat fact",
                "parameters": {"type": "object", "properties": {}}
            }
        }
    ]

    response = await litellm.acompletion(
        model="ollama/gemma3:4B",
        api_base="http://172.27.160.1:11434",
        messages=[{"role": "user", "content": "Tell me a cat fact"}],
        tools=tools,
        temperature=0,
        max_tokens=512,
        keep_alive="30m",
    )

    msg = response.choices[0].message
    print(f"Content: {repr(msg.content)[:300]}")
    print(f"Tool calls: {msg.tool_calls}")
    print(f"Finish reason: {response.choices[0].finish_reason}")

    if msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"  Function: {tc.function.name}")
            print(f"  Args: {tc.function.arguments}")

asyncio.run(test())
