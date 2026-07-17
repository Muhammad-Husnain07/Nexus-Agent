"""Multi-turn conversation test — proves history persists across invocations.

Builds an agent graph with MemorySaver, runs two turns with the same
thread_id, and verifies the second turn's LLM call receives the first
turn's messages in its history.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from nexus.agent.graph import build_agent_graph
from nexus.agent.runner import AgentRunner
from nexus.llm.client import LLMResponse, UsageInfo
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ToolExecutor
from nexus.tools.result import ToolResult


@pytest.fixture(autouse=True)
def _test_env() -> None:
    """Disable HITL and sandbox for integration tests."""
    os.environ["NEXUS_AGENT__HITL_DEFAULT"] = "false"
    os.environ["NEXUS_TOOLS__SANDBOX_ENABLED"] = "false"
    from nexus.config.settings import get_settings
    get_settings.cache_clear()


_BASE_RESPONSE = LLMResponse(
    content="",
    usage=UsageInfo(prompt_tokens=10, completion_tokens=20, total_tokens=30),
    model="gpt-4o",
    provider="openai",
    latency_ms=50,
    cost_usd=0.001,
)


@pytest.fixture
def tool_selector() -> DynamicToolSelector:
    sel = MagicMock(spec=DynamicToolSelector)
    sel.select = AsyncMock(return_value=[])
    return sel


_ECHO_RESULT = ToolResult(
    tool_id="00000000-0000-0000-0000-000000000010",
    tool_name="echo",
    status="success",
    data={"echo": "hello"},
    duration_ms=5,
)


class TurnAwareMockLLM:
    """LLMClient that returns canned responses and records call history.

    Captures the messages each call received so the test can assert
    the second turn sees the first turn's history.
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.call_args: list[dict] = []

    async def complete(self, **kwargs: object) -> LLMResponse:
        self.call_count += 1
        self.call_args.append(kwargs)

        # Turn 1: understand_intent — extract intent, no missing slots
        if self.call_count == 1:
            return _BASE_RESPONSE.model_copy(
                update={
                    "content": json.dumps({
                        "intent": "store_user_name",
                        "parameters": {"name": "Alice"},
                        "missing_info_slots": [],
                    })
                }
            )
        # Turn 1: plan — create single echo step
        if self.call_count == 2:
            return _BASE_RESPONSE.model_copy(
                update={
                    "content": json.dumps({
                        "steps": [{
                            "id": "step_1",
                            "description": "Echo back the user's name",
                            "tool_name": "echo",
                            "inputs": {"msg": "Alice"},
                            "depends_on": [],
                            "expected_outcome": "Echo response received",
                            "is_destructive": False,
                        }],
                        "rationale": "Simple echo to confirm understanding",
                        "estimated_tool_calls": 1,
                        "reversible": True,
                        "needs_human_review": False,
                    })
                }
            )
        # Turn 1: execute_step — call echo tool
        if self.call_count == 3:
            return _BASE_RESPONSE.model_copy(
                update={
                    "content": "",
                    "tool_calls": [{
                        "id": "call_echo_1",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": json.dumps({"msg": "Alice"}),
                        },
                    }],
                }
            )
        # Turn 1: analyze_results — succeed, finalize
        if self.call_count == 4:
            return _BASE_RESPONSE.model_copy(
                update={
                    "content": json.dumps({
                        "outcome": "success",
                        "next_action": "finalize",
                        "reasoning": "Echo completed successfully",
                    })
                }
            )
        # Turn 1: finalize — compose final answer
        if self.call_count == 5:
            return _BASE_RESPONSE.model_copy(
                update={"content": "Nice to meet you, Alice!"}
            )

        # ── Turn 2 ──────────────────────────────────────────────────────
        # Turn 2: understand_intent
        if self.call_count == 6:
            # Check that messages history contains turn 1 exchange
            msgs = kwargs.get("messages", [])
            assert len(msgs) > 1, (
                f"Turn 2 should see >1 messages (saw {len(msgs)}). "
                "Conversation history was not persisted across invocations."
            )
            # Verify the first exchange is visible
            user_msgs = [m for m in msgs if m.get("role") == "user"]
            assert any("Alice" in str(m.get("content", "")) for m in user_msgs), (
                "Turn 2 did not see 'Alice' from turn 1 in message history"
            )
            return _BASE_RESPONSE.model_copy(
                update={
                    "content": json.dumps({
                        "intent": "recall_user_name",
                        "parameters": {},
                        "missing_info_slots": [],
                    })
                }
            )
        # Turn 2: plan
        if self.call_count == 7:
            return _BASE_RESPONSE.model_copy(
                update={
                    "content": json.dumps({
                        "steps": [],
                        "rationale": "No tools needed, just answer from memory",
                        "estimated_tool_calls": 0,
                        "reversible": True,
                        "needs_human_review": False,
                    })
                }
            )
        # Turn 2: finalize — answer from context
        return _BASE_RESPONSE.model_copy(
            update={"content": "Your name is Alice."}
        )


@pytest.fixture
def llm() -> TurnAwareMockLLM:
    return TurnAwareMockLLM()


@pytest.fixture
def tool_executor() -> ToolExecutor:
    exec_mock = MagicMock(spec=ToolExecutor)
    exec_mock.execute = AsyncMock(return_value=_ECHO_RESULT)
    return exec_mock


@pytest.mark.asyncio
async def test_multi_turn_history_persists(
    llm: TurnAwareMockLLM,
    tool_selector: DynamicToolSelector,
    tool_executor: ToolExecutor,
) -> None:
    """Run two turns with the same session/thread_id and verify history."""
    checkpointer = MemorySaver()

    session_id = "test-multi-turn-session"
    tid = "00000000-0000-0000-0000-000000000001"
    uid = "00000000-0000-0000-0000-000000000002"

    runner = AgentRunner(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        checkpointer=checkpointer,
    )

    # Turn 1: introduce Alice
    turn1_events = []
    async for event in runner.invoke(
        session_id=session_id,
        user_message="My name is Alice",
        tenant_id=tid,
        user_id=uid,
        config={"configurable": {"thread_id": session_id}},
    ):
        turn1_events.append(event)

    turn1_final = [e for e in turn1_events if e.type == "final_response"]
    assert len(turn1_final) == 1, "Turn 1 should produce a final_response"
    assert "Alice" in turn1_final[0].payload.get("text", "")

    # Turn 2: ask what my name is (same thread_id)
    turn2_events = []
    async for event in runner.invoke(
        session_id=session_id,
        user_message="What is my name?",
        tenant_id=tid,
        user_id=uid,
        config={"configurable": {"thread_id": session_id}},
    ):
        turn2_events.append(event)

    turn2_final = [e for e in turn2_events if e.type == "final_response"]
    assert len(turn2_final) == 1, "Turn 2 should produce a final_response"
    assert "Alice" in turn2_final[0].payload.get("text", "")

    # Verify LLM saw the history (assertions inside mock already check this)
    assert llm.call_count > 5, f"Expected >5 LLM calls across 2 turns, got {llm.call_count}"

    # Verify messages grew between turns
    verify_graph = build_agent_graph(
        llm_client=llm,
        tool_selector=tool_selector,
        tool_executor=tool_executor,
        checkpointer=checkpointer,
    )
    state = await verify_graph.aget_state({"configurable": {"thread_id": session_id}})
    msgs = state.values.get("messages", [])
    assert len(msgs) > 1, (
        f"Checkpoint should contain >1 messages across 2 turns, got {len(msgs)}"
    )
