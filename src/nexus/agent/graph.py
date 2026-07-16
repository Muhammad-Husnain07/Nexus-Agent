"""LangGraph StateGraph — hybrid ReAct + Plan-and-Execute orchestration.

Nodes
-----
* ``understand_intent`` — parse user message into structured intent
* ``gather_requirements`` — ask clarifying questions when info is missing
* ``discover_tools`` — find relevant tools via ``DynamicToolSelector``
* ``plan`` — generate a step-by-step plan via LLM structured output
* ``select_and_bind_tools`` — pre-filter tools for the current plan step
* ``execute_step`` — ReAct micro-loop for the current plan step
* ``present_preview`` — interrupt for human feedback on intermediate results
* ``analyze_results`` — review results and decide next action
* ``finalize`` — compose the final answer
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from nexus.agent.errors import PlanningError
from nexus.agent.state import AgentState
from nexus.config.settings import AgentSettings, get_settings
from nexus.llm.client import LLMClient
from nexus.redis_client.pubsub import EventBus, agent_channel
from nexus.tools.approval_gate import check_approval_required
from nexus.tools.discovery import DynamicToolSelector
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.agent.graph")

_INTENT_SYSTEM_PROMPT = """\
You are an intent parser. Given a user message, extract the structured intent.
Return JSON with:
- "intent": a short verb-noun phrase describing the goal
- "parameters": dict of extracted parameters (empty dict if none)
- "missing_info_slots": list of required info not provided (empty list if all present)
"""

_PLAN_SYSTEM_PROMPT = """\
You are a planning agent. Given available tools and user intent, create a step-by-step plan.
Each step must have:
- "id": unique string like "step_1"
- "description": what this step does
- "tool_name": which tool to use (or null if no tool)
- "inputs": dict of input parameters (or null)
- "status": "pending"
- "depends_on": list of prerequisite step IDs

Return JSON with a "steps" array."""

_ANALYZE_SYSTEM_PROMPT = """\
You are a result analyzer. Review the tool execution results and decide the next action.
Return JSON with:
- "decision": one of "continue", "revise", "ask", "preview", "finalize"
- "reason": brief explanation
"""


def _tool_to_openai_schema(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert a ToolRead dict to OpenAI tool-call schema."""
    schema = tool.get("input_schema") or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": schema,
        },
    }


def _openai_message(role: str, content: str, **kwargs: Any) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": role, "content": content}
    msg.update(kwargs)
    return msg


def _get_current_step(state: AgentState) -> dict[str, Any] | None:
    plan: list[dict[str, Any]] | None = state.get("plan")
    if not plan:
        return None
    idx: int = state.get("current_step_index", 0)
    if 0 <= idx < len(plan):
        return plan[idx]
    return None


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------


async def understand_intent(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Parse the latest user message into structured intent + missing info slots."""
    messages: list[dict[str, Any]] = list(state.get("messages", []))
    last_user = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    if not last_user:
        return {"intent": None, "missing_info_slots": [], "_routing_decision": "finalize"}

    response = await llm.complete(
        model=model,
        messages=[
            _openai_message("system", _INTENT_SYSTEM_PROMPT),
            _openai_message("user", last_user),
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    try:
        parsed: dict[str, Any] = json.loads(response.content or "{}")
    except (json.JSONDecodeError, TypeError):
        logger.warning("intent.parse_failed", content=response.content)
        parsed = {"intent": "", "parameters": {}, "missing_info_slots": []}

    intent = parsed.get("intent", "")
    missing: list[str] = parsed.get("missing_info_slots", [])
    messages.append(_openai_message("assistant", f"Parsed intent: {intent}"))

    return {
        "messages": messages,
        "intent": {"intent": intent, "parameters": parsed.get("parameters", {})},
        "missing_info_slots": missing,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


async def gather_requirements(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Ask clarifying questions when required information is missing."""
    missing: list[str] = state.get("missing_info_slots") or []
    if not missing:
        return {"final_response": None, "missing_info_slots": []}

    prompt = (
        "The user has not provided the following required information:\n"
        + "\n".join(f"- {slot}" for slot in missing)
        + "\n\nPolitely ask the user to provide these details."
    )
    response = await llm.complete(
        model=model,
        messages=[
            _openai_message("system", "You are a helpful assistant gathering requirements."),
            _openai_message("user", prompt),
        ],
        temperature=0.7,
    )
    question: str = response.content or "Could you please provide more details?"

    messages: list[dict[str, Any]] = list(state.get("messages", []))
    messages.append(_openai_message("assistant", question))

    return {
        "messages": messages,
        "final_response": question,
        "missing_info_slots": [],
        "_routing_decision": "ask",
    }


async def discover_tools(
    state: AgentState,
    selector: DynamicToolSelector,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Discover relevant tools for the user's intent."""
    tenant_id = uuid.UUID(state["tenant_id"])
    intent: dict[str, Any] = state.get("intent") or {}
    query: str = intent.get("intent", "") or state.get("messages", [{}])[-1].get("content", "")

    session = session_factory() if session_factory else None
    tools = await selector.select(session, tenant_id=tenant_id, message=query)
    tool_dicts: list[dict[str, Any]] = [t.model_dump(mode="json") for t in tools]
    return {"available_tools": tool_dicts}


async def plan(
    state: AgentState,
    llm: LLMClient,
    model: str,
    settings: AgentSettings,
) -> dict[str, Any]:
    """Generate a plan via LLM structured output."""
    tools: list[dict[str, Any]] = state.get("available_tools", [])
    tool_descriptions = [
        {"name": t["name"], "description": t.get("description", "")} for t in tools
    ]
    intent: dict[str, Any] = state.get("intent") or {}

    response = await llm.complete(
        model=model,
        messages=[
            _openai_message("system", _PLAN_SYSTEM_PROMPT),
            _openai_message(
                "user",
                json.dumps(
                    {
                        "intent": intent,
                        "available_tools": tool_descriptions,
                        "max_steps": settings.max_plan_steps,
                    }
                ),
            ),
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    try:
        parsed: dict[str, Any] = json.loads(response.content or "{}")
    except (json.JSONDecodeError, TypeError):
        raise PlanningError("Failed to parse plan from LLM output") from None

    steps_raw: list[dict[str, Any]] = parsed.get("steps", [])
    if not steps_raw:
        raise PlanningError("LLM returned empty plan")

    steps: list[dict[str, Any]] = []
    for s in steps_raw:
        steps.append(
            {
                "id": s.get("id", f"step_{len(steps) + 1}"),
                "description": s.get("description", ""),
                "tool_name": s.get("tool_name"),
                "inputs": s.get("inputs"),
                "status": "pending",
                "depends_on": s.get("depends_on", []),
            }
        )

    return {"plan": steps, "current_step_index": 0}


async def select_and_bind_tools(state: AgentState) -> dict[str, Any]:
    """Pre-filter and bind tools relevant to the current plan step."""
    step = _get_current_step(state)
    if step is None:
        return {"_bound_tools": [], "_routing_decision": "finalize"}

    tools: list[dict[str, Any]] = state.get("available_tools", [])
    step_tool_name: str | None = step.get("tool_name")

    if step_tool_name:
        bound = [t for t in tools if t["name"] == step_tool_name]
        if not bound:
            logger.warning("tool.not_found_for_step", tool=step_tool_name, step=step["id"])
    else:
        bound = tools  # no specific tool required

    schemas = [_tool_to_openai_schema(t) for t in bound]
    return {"_bound_tools": schemas}


async def execute_step(  # noqa: PLR0912, PLR0913, PLR0915
    state: AgentState,
    llm: LLMClient,
    executor: ToolExecutor,
    model: str,
    settings: AgentSettings,
    event_bus: EventBus | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """ReAct micro-loop for the current plan step."""
    step = _get_current_step(state)
    if step is None:
        return {"_routing_decision": "finalize"}

    tools: list[dict[str, Any]] = state.get("available_tools", [])
    tool_map: dict[str, dict[str, Any]] = {t["name"]: t for t in tools}

    if step.get("tool_name") and step["tool_name"] not in tool_map:
        step["status"] = "failed"
        plan = list(state.get("plan") or [])
        plan[state["current_step_index"]] = step
        return {
            "plan": plan,
            "errors": state.get("errors", []) + [f"Tool '{step['tool_name']}' not found"],
            "_routing_decision": "revise",
        }

    sub_iterations: int = 0
    max_sub: int = 5
    messages: list[dict[str, Any]] = list(state.get("messages", []))
    tool_results: list[dict[str, Any]] = list(state.get("tool_results", []))
    errors: list[str] = list(state.get("errors", []))

    tool_descriptions = [
        {"name": t["name"], "description": t.get("description", "")} for t in tools
    ]
    system_content = "You are a helpful assistant that solves tasks by invoking tools."
    if tool_descriptions:
        system_content += "\n\nAvailable tools:\n" + json.dumps(tool_descriptions, indent=2)

    current_messages: list[dict[str, Any]] = [
        _openai_message("system", system_content),
    ]
    step_description = step.get("description", "")
    step_inputs = step.get("inputs", {})
    current_messages.append(
        _openai_message(
            "user",
            f"Execute step: {step_description}\nInputs: {json.dumps(step_inputs)}",
        )
    )

    openai_tools: list[dict[str, Any]] | None = state.get("_bound_tools") or (
        [_tool_to_openai_schema(t) for t in tools] if tools else None
    )

    while sub_iterations < max_sub:
        sub_iterations += 1

        response = await llm.complete(
            model=model,
            messages=current_messages,
            tools=openai_tools,
            temperature=0,
        )

        if response.tool_calls:
            for tc in response.tool_calls:
                func_name: str = tc.get("function", {}).get("name", "")
                raw_args: str = tc.get("function", {}).get("arguments", "{}")
                try:
                    func_args: dict[str, Any] = (
                        json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    )
                except json.JSONDecodeError:
                    func_args = {}

                tool_def = tool_map.get(func_name)
                if tool_def is None:
                    errors.append(f"LLM requested unknown tool '{func_name}'")
                    current_messages.append(
                        _openai_message("assistant", content="", tool_calls=[tc])
                    )
                    current_messages.append(
                        _openai_message(
                            "tool",
                            content=f"Error: unknown tool '{func_name}'",
                            tool_call_id=tc.get("id", ""),
                        )
                    )
                    continue

                # Publish tool_call_started
                if event_bus:
                    await event_bus.publish(
                        agent_channel(state["session_id"]),
                        {"type": "tool_call_started", "tool_name": func_name, "inputs": func_args},
                    )

                tool_read = ToolRead(**tool_def)
                ctx = ExecutionContext(
                    tenant_id=uuid.UUID(state["tenant_id"]),
                    user_id=uuid.UUID(state["user_id"]),
                    session_id=uuid.UUID(state["session_id"]),
                )

                # Approval gate
                check = check_approval_required(
                    tool_read,
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    session_id=ctx.session_id,
                    settings=settings,
                )
                if check.required:
                    # Publish approval_required
                    approval_payload = {
                        "type": "approval_required",
                        "tool_name": func_name,
                        "inputs": func_args,
                    }
                    if event_bus:
                        await event_bus.publish(
                            agent_channel(state["session_id"]),
                            approval_payload,
                        )

                    value = interrupt(approval_payload)
                    if not isinstance(value, dict) or not value.get("approved"):
                        errors.append(f"Approval rejected for tool '{func_name}'")
                        step["status"] = "skipped"
                        plan = list(state.get("plan") or [])
                        plan[state["current_step_index"]] = step
                        return {
                            "plan": plan,
                            "errors": errors,
                            "_routing_decision": "finalize",
                            "pending_approval": None,
                        }

                # Execute
                session = session_factory() if session_factory else None
                try:
                    result = await executor.execute(
                        tool_read,
                        func_args,
                        ctx,
                        skip_approval=True,
                        session=session,
                    )
                except Exception as exc:
                    errors.append(f"Tool '{func_name}' execution error: {exc}")
                    result = ToolResult(
                        tool_id=tool_read.id,
                        tool_name=func_name,
                        status="error",
                        error=str(exc),
                    )

                result_dict = result.model_dump(mode="json")
                tool_results.append(result_dict)

                current_messages.append(_openai_message("assistant", content="", tool_calls=[tc]))
                current_messages.append(
                    _openai_message(
                        "tool",
                        content=json.dumps(
                            result_dict.get("data") or {"error": result_dict.get("error")}
                        ),
                        tool_call_id=tc.get("id", ""),
                    )
                )

                if event_bus:
                    await event_bus.publish(
                        agent_channel(state["session_id"]),
                        {
                            "type": "tool_call_completed",
                            "tool_name": func_name,
                            "status": result.status,
                        },
                    )
        else:
            content: str = response.content or ""
            current_messages.append(_openai_message("assistant", content))
            messages.append(_openai_message("assistant", content))
            break

    step["status"] = "done" if not errors else "failed"
    plan = list(state.get("plan") or [])
    plan[state["current_step_index"]] = step

    scratchpad: str = state.get("scratchpad", "")
    scratchpad += f"\n--- Step {state['current_step_index']} ---\n"
    scratchpad += json.dumps(tool_results[-1] if tool_results else {"note": step["status"]})

    return {
        "messages": messages,
        "plan": plan,
        "tool_results": tool_results,
        "errors": errors,
        "scratchpad": scratchpad,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "_routing_decision": "continue",
    }


async def present_preview(state: AgentState) -> dict[str, Any]:
    """Show intermediate result and interrupt for human feedback."""
    tool_results: list[dict[str, Any]] = state.get("tool_results", [])
    last = tool_results[-1] if tool_results else {}

    payload = {
        "type": "intermediate_preview",
        "data": last.get("data"),
        "tool_name": last.get("tool_name"),
        "status": last.get("status"),
    }

    value = interrupt(payload)

    if isinstance(value, dict) and value.get("continue") is False:
        return {
            "final_response": "Execution paused by user.",
            "_routing_decision": "finalize",
        }

    return {"_routing_decision": "continue"}


async def analyze_results(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Review tool results and decide next action."""
    plan: list[dict[str, Any]] | None = state.get("plan")
    step: dict[str, Any] | None = _get_current_step(state)
    decision: str = "finalize"

    if plan and step is not None:
        idx: int = state.get("current_step_index", 0)
        next_idx: int = idx + 1

        deps = step.get("depends_on", [])
        deps_met = all(any(p["id"] == dep and p["status"] == "done" for p in plan) for dep in deps)

        if not deps_met:
            decision = "continue"
        elif step.get("status") == "done" and next_idx < len(plan):
            step["status"] = "done"
            plan[idx] = step
            decision = "continue"
            return {
                "plan": plan,
                "current_step_index": next_idx,
                "_routing_decision": decision,
            }
        elif step.get("status") == "done" and next_idx >= len(plan):
            decision = "finalize"
        elif step.get("status") == "failed":
            prompt = f"Step '{step['description']}' failed.\nDecide: revise, ask, preview, finalize"
            response = await llm.complete(
                model=model,
                messages=[
                    _openai_message("system", _ANALYZE_SYSTEM_PROMPT),
                    _openai_message("user", prompt),
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            try:
                parsed: dict[str, Any] = json.loads(response.content or "{}")
                decision = parsed.get("decision", "finalize")
            except (json.JSONDecodeError, TypeError):
                decision = "finalize"

    return {"_routing_decision": decision}


async def finalize(
    state: AgentState,
    llm: LLMClient,
    model: str,
) -> dict[str, Any]:
    """Compose the final answer from accumulated results."""
    results: list[dict[str, Any]] = state.get("tool_results", [])
    errors: list[str] = state.get("errors", [])

    if errors and not results:
        final = "I encountered some issues:\n" + "\n".join(f"- {e}" for e in errors)
    elif results:
        summary = json.dumps([r.get("data") for r in results if r.get("data")], indent=2)
        response = await llm.complete(
            model=model,
            messages=[
                _openai_message(
                    "user",
                    f"Summarise the following tool execution results for the user:\n{summary}",
                )
            ],
            temperature=0.7,
        )
        final = response.content or "Task completed."
    else:
        final = "No results were produced."

    messages: list[dict[str, Any]] = list(state.get("messages", []))
    messages.append(_openai_message("assistant", final))

    return {
        "final_response": final,
        "messages": messages,
        "_routing_decision": "finalize",
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_understand(state: AgentState) -> str:
    """If missing_info_slots is non-empty, ask clarifying questions."""
    missing: list[str] = state.get("missing_info_slots") or []
    if missing:
        return "gather_requirements"
    return "discover_tools"


def route_after_analyze(state: AgentState) -> str:
    """Route to the next node based on the analyzer's decision."""
    decision: str = state.get("_routing_decision", "finalize")
    max_iter: int = get_settings().agent.max_iterations
    if state.get("iteration_count", 0) >= max_iter:
        return "finalize"
    if decision == "preview":
        return "present_preview"
    return decision


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _node(fn: Any, *args: Any, **kwargs: Any) -> Callable[[AgentState], Any]:
    """Wrap a node function with pre-bound dependencies."""

    async def wrapper(state: AgentState) -> dict[str, Any]:
        return await fn(state, *args, **kwargs)

    return wrapper


def build_agent_graph(  # noqa: PLR0913
    llm_client: LLMClient | None = None,
    tool_selector: DynamicToolSelector | None = None,
    tool_executor: ToolExecutor | None = None,
    event_bus: EventBus | None = None,
    model: str | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> StateGraph:
    """Build and compile the LangGraph agent graph.

    Args:
        llm_client: LLM client for completions.  Creates a default if None.
        tool_selector: Dynamic tool discovery.  Required.
        tool_executor: Tool execution engine.  Required.
        event_bus: Redis event bus for streaming events.
        model: Model override (defaults to ``settings.llm.default_model``).
        session_factory: Async callable returning a DB ``AsyncSession``.

    Returns:
        A compiled ``StateGraph`` ready for invocation.
    """
    _llm = llm_client or LLMClient()
    settings = get_settings()
    _model = model or settings.llm.default_model
    _settings = settings.agent

    graph = StateGraph(AgentState)

    graph.add_node("understand_intent", _node(understand_intent, _llm, _model))
    graph.add_node("gather_requirements", _node(gather_requirements, _llm, _model))
    graph.add_node("discover_tools", _node(discover_tools, tool_selector, session_factory))
    graph.add_node("plan", _node(plan, _llm, _model, _settings))
    graph.add_node("select_and_bind_tools", _node(select_and_bind_tools))
    graph.add_node(
        "execute_step",
        _node(execute_step, _llm, tool_executor, _model, _settings, event_bus, session_factory),
    )
    graph.add_node("present_preview", _node(present_preview))
    graph.add_node("analyze_results", _node(analyze_results, _llm, _model))
    graph.add_node("finalize", _node(finalize, _llm, _model))

    graph.set_entry_point("understand_intent")

    graph.add_conditional_edges(
        "understand_intent",
        route_after_understand,
        {"gather_requirements": "gather_requirements", "discover_tools": "discover_tools"},
    )

    graph.add_edge("gather_requirements", END)
    graph.add_edge("discover_tools", "plan")
    graph.add_edge("plan", "select_and_bind_tools")
    graph.add_edge("select_and_bind_tools", "execute_step")
    graph.add_edge("execute_step", "analyze_results")

    graph.add_conditional_edges(
        "analyze_results",
        route_after_analyze,
        {
            "continue": "select_and_bind_tools",
            "revise": "plan",
            "ask": "gather_requirements",
            "preview": "present_preview",
            "finalize": "finalize",
        },
    )

    graph.add_conditional_edges(
        "present_preview",
        lambda s: s.get("_routing_decision", "continue"),
        {"continue": "select_and_bind_tools", "finalize": "finalize"},
    )

    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=MemorySaver())
