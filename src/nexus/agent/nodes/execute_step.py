"""execute_step node — ReAct micro-loop for the current plan step."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

import jsonschema
import structlog

from nexus.agent import hitl
from nexus.agent.errors import ApprovalRejected
from nexus.agent.hitl_middleware import HITLMiddleware
from nexus.agent.prompts import prompt_manager
from nexus.agent.state import AgentState
from nexus.config.settings import AgentSettings
from nexus.llm.client import LLMClient
from nexus.redis_client.pubsub import EventBus, agent_channel
from nexus.tools.executor import ExecutionContext, ToolExecutor
from nexus.tools.result import ToolResult
from nexus.tools.schemas import ToolRead

logger = structlog.get_logger("nexus.agent.nodes.execute_step")

_MAX_SUB_ITERATIONS = 5
_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")


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


def _tool_to_openai_schema(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("input_schema") or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": schema,
        },
    }


def _resolve_placeholders(
    raw_inputs: dict[str, Any],
    gathered: dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve ``${...}`` placeholders in step inputs."""

    def _resolve(val: str) -> str:
        def _replacer(match: re.Match) -> str:
            key = match.group(1)
            # Try gathered_requirements first
            if key in gathered:
                return str(gathered[key])
            # Try dot-notation for nested access
            parts = key.split(".", 1)
            if len(parts) == 2:
                prefix, suffix = parts
                if prefix == "step" and suffix.startswith("_") and len(parts) > 2:
                    pass
                # Try result references like step_1.result
                for r in tool_results:
                    r_tool = r.get("tool_name", "")
                    if prefix == r_tool or prefix == r.get("tool_call_id", ""):
                        data = r.get("data", {})
                        if isinstance(data, dict) and suffix in data:
                            return str(data[suffix])
                # Try user.email as a key
                if key == "user.email":
                    return "${{user.email}}"  # Keep as literal if not resolved
            return f"${{{key}}}"  # Keep as literal
        return _PLACEHOLDER_RE.sub(_replacer, val)

    resolved: dict[str, Any] = {}
    for k, v in raw_inputs.items():
        if isinstance(v, str):
            resolved[k] = _resolve(v)
        elif isinstance(v, dict):
            resolved[k] = {sk: _resolve(sv) if isinstance(sv, str) else sv for sk, sv in v.items()}
        else:
            resolved[k] = v
    return resolved


def _validate_inputs(
    resolved: dict[str, Any],
    schema: dict[str, Any] | None,
) -> str | None:
    """Validate resolved inputs against JSON Schema.  Returns error or None."""
    if not schema or schema == {"type": "object", "properties": {}}:
        return None
    try:
        jsonschema.validate(resolved, schema)
        return None
    except jsonschema.ValidationError as exc:
        return str(exc)


async def execute_step(  # noqa: PLR0912, PLR0913, PLR0915
    state: AgentState,
    llm: LLMClient,
    executor: ToolExecutor,
    model: str,
    settings: AgentSettings,
    event_bus: EventBus | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """ReAct micro-loop for the current plan step with full production features.

    - Resolves ``${...}`` placeholders from ``gathered_requirements`` + tool_results
    - Validates resolved inputs against ``tool.input_schema``
    - LLM-driven correction (1 retry) on validation failure
    - Sets ``pending_approval`` before HITL interrupt
    - On tool error: decides retry / revise / ask via small LLM call

    Returns:
        Dict with updated ``plan``, ``messages``, ``tool_results``, ``errors``,
        ``scratchpad``, and ``_routing_decision``.
    """
    step = _get_current_step(state)
    if step is None:
        return {"_routing_decision": "finalize"}

    tools: list[dict[str, Any]] = state.get("available_tools", [])
    tool_map: dict[str, dict[str, Any]] = {t["name"]: t for t in tools}

    if step.get("tool_name") and step["tool_name"] not in tool_map:
        step["status"] = "failed"
        plan_list = list(state.get("plan") or [])
        plan_list[state["current_step_index"]] = step
        return {
            "plan": plan_list,
            "errors": state.get("errors", []) + [f"Tool '{step['tool_name']}' not found"],
            "_routing_decision": "revise",
        }

    sub_iterations: int = 0
    messages: list[dict[str, Any]] = list(state.get("messages", []))
    tool_results: list[dict[str, Any]] = list(state.get("tool_results", []))
    errors: list[str] = list(state.get("errors", []))

    system_content = prompt_manager.render("execute_step", additional_context="")
    tool_descriptions = [
        {"name": t["name"], "description": t.get("description", "")} for t in tools
    ]
    if tool_descriptions:
        system_content += "\n\nAvailable tools:\n" + json.dumps(tool_descriptions, indent=2)

    # Resolve placeholders in step inputs
    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    step_inputs_raw: dict[str, Any] = step.get("inputs") or {}
    step_inputs = _resolve_placeholders(step_inputs_raw, gathered, tool_results)

    current_messages: list[dict[str, Any]] = [
        _openai_message("system", system_content),
    ]
    step_description = step.get("description", "")
    current_messages.append(
        _openai_message(
            "user",
            f"Execute step: {step_description}\nInputs: {json.dumps(step_inputs)}",
        )
    )

    openai_tools: list[dict[str, Any]] | None = state.get("_bound_tools") or (
        [_tool_to_openai_schema(t) for t in tools] if tools else None
    )

    while sub_iterations < _MAX_SUB_ITERATIONS:
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

                # Validate resolved inputs before execution (1 correction retry)
                input_schema = tool_def.get("input_schema")
                validation_error = _validate_inputs(func_args, input_schema)
                if validation_error:
                    correction_prompt = prompt_manager.render(
                        "execute_step_correction",
                        tool_name=func_name,
                        schema=json.dumps(input_schema, indent=2),
                        inputs=json.dumps(func_args, indent=2),
                        error=validation_error,
                    )
                    correction_response = await llm.complete(
                        model=model,
                        messages=[
                            _openai_message("system", "Fix the tool inputs to match the schema."),
                            _openai_message("user", correction_prompt),
                        ],
                        response_format={"type": "json_object"},
                        temperature=0,
                    )
                    try:
                        fixed = json.loads(correction_response.content or "{}")
                        func_args = fixed.get("inputs", func_args)
                        # Re-validate
                        validation_error = _validate_inputs(func_args, input_schema)
                    except (json.JSONDecodeError, TypeError):
                        pass

                    if validation_error:
                        errors.append(
                            f"Input validation failed for '{func_name}': {validation_error}"
                        )
                        current_messages.append(
                            _openai_message(
                                "tool",
                                content=f"Validation error: {validation_error}",
                                tool_call_id=tc.get("id", ""),
                            )
                        )
                        continue

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

                # HITL approval gate via middleware
                approval_state_update: dict[str, Any] = {}
                if hitl.requires_approval(tool_read, step, settings):
                    payload = hitl.build_approval_payload(tool_read, step, func_args)
                    approval_state_update = {"pending_approval": payload}

                session = session_factory() if session_factory else None
                middleware = HITLMiddleware(executor, settings)
                try:
                    result = await middleware.execute(
                        tool_read=tool_read,
                        plan_step=step,
                        func_args=func_args,
                        context=ctx,
                        event_bus=event_bus,
                        session_id=state["session_id"],
                        db_session=session,
                    )
                except ApprovalRejected as exc:
                    errors.append(f"Approval rejected for tool '{func_name}': {exc}")
                    step["status"] = "skipped"
                    plan_list = list(state.get("plan") or [])
                    plan_list[state["current_step_index"]] = step
                    result = {
                        "plan": plan_list,
                        "errors": errors,
                        "_routing_decision": "continue",
                        "pending_approval": None,
                    }
                    result.update(approval_state_update)
                    return result
                except Exception as exc:
                    errors.append(f"Tool '{func_name}' execution error: {exc}")
                    result = ToolResult(
                        tool_id=tool_read.id,
                        tool_name=func_name,
                        status="error",
                        error=str(exc),
                    )

                    # Error recovery — decide retry / revise / ask
                    recovery_prompt = prompt_manager.render(
                        "execute_step_error_recovery",
                        step_description=step_description,
                        tool_name=func_name,
                        error=str(exc),
                        previous_results=json.dumps(
                            tool_results[-1] if tool_results else {}, indent=2
                        ),
                    )
                    recovery_response = await llm.complete(
                        model=model,
                        messages=[
                            _openai_message(
                                "system", "Decide what to do after a tool execution failure."
                            ),
                            _openai_message("user", recovery_prompt),
                        ],
                        response_format={"type": "json_object"},
                        temperature=0,
                    )
                    try:
                        recovery = json.loads(recovery_response.content or "{}")
                        recovery_action = recovery.get("action", "ask")
                        if recovery_action == "retry":
                            modified = recovery.get("modified_inputs", func_args)
                            func_args = modified
                            continue  # retry the current iteration
                        if recovery_action == "revise":
                            return {
                                "plan": list(state.get("plan") or []),
                                "errors": errors,
                                "_routing_decision": "revise",
                                "pending_approval": None,
                            }
                        # else "ask" — surface to user
                    except (json.JSONDecodeError, TypeError):
                        pass

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
    plan_list = list(state.get("plan") or [])
    plan_list[state["current_step_index"]] = step

    scratchpad: str = state.get("scratchpad", "")
    scratchpad += f"\n--- Step {state['current_step_index']} ---\n"
    scratchpad += json.dumps(tool_results[-1] if tool_results else {"note": step["status"]})

    return {
        "messages": messages,
        "plan": plan_list,
        "tool_results": tool_results,
        "errors": errors,
        "scratchpad": scratchpad,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "_routing_decision": "continue",
    }
