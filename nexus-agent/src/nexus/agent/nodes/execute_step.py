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


def _get_nested(data: Any, path: str) -> Any:
    """Traverse a nested dict/array using dot-separated path.
    When the exact path fails, strips leading 'result.' prefix and retries
    (handles LLM paths like 'result.longitude' when data has 'results[0].longitude')."""
    paths_to_try = [path]
    # Also try without "result." prefix (LLM often uses result.field but data stores at top level)
    if path.startswith("result."):
        paths_to_try.append(path[7:])

    for p in paths_to_try:
        current = data
        parts = p.split(".")
        found = True
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    found = False
                    break
            elif isinstance(current, list):
                matched = None
                for item in current:
                    if isinstance(item, dict) and part in item:
                        matched = item[part]
                        break
                if matched is not None:
                    current = matched
                else:
                    found = False
                    break
            else:
                found = False
                break
        if found:
            return current
    return None


def _resolve_placeholders(
    raw_inputs: dict[str, Any],
    gathered: dict[str, Any],
    tool_results: list[dict[str, Any]],
    user_context: dict[str, Any] | None = None,
    plan_steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve ``${...}`` placeholders in step inputs.

    Supports:
      - ``${step_X.result}`` — the full data from the tool result of step X
      - ``${step_X.result.field.nested}`` — deep access into result data
      - ``${tool_name.field}`` — result from the most recent tool execution
      - ``${gathered.field}`` — gathered requirements
      - ``${user.field}`` — user context
    """

    def _find_tool_result(prefix: str) -> dict[str, Any] | None:
        """Find the LATEST tool result by tool name, step ID, or step index."""
        # Build a reverse-chronological list so first match = most recent
        reversed_results = list(reversed(tool_results))

        # Try exact tool name match (most recent first)
        for r in reversed_results:
            if r.get("tool_name") == prefix:
                return r

        # Try step ID match (step_1, step_2, etc.) using plan_steps
        if plan_steps and prefix.startswith("step_"):
            try:
                step_idx = int(prefix.split("_")[1]) - 1
                if 0 <= step_idx < len(plan_steps):
                    target_tool = plan_steps[step_idx].get("tool_name")
                    if target_tool:
                        for r in reversed_results:
                            if r.get("tool_name") == target_tool:
                                return r
            except (ValueError, IndexError):
                pass

        # Try tool_call_id match
        for r in reversed_results:
            if r.get("tool_call_id") == prefix:
                return r
        return None

    def _replacer(match: re.Match) -> str:
        key = match.group(1)

        # Try gathered_requirements first
        if key.startswith("gathered."):
            sub = key[9:]
            val = _get_nested(gathered, sub)
            if val is not None:
                return str(val)

        if key in gathered:
            return str(gathered[key])

        # Try user.* placeholders
        if key.startswith("user.") and user_context:
            val = _get_nested(user_context, key[5:])
            if val is not None:
                return str(val)

        # Try tool result references: tool_name.field or step_X.result.nested
        if "." in key:
            prefix, _, rest = key.partition(".")
            if rest:
                result = _find_tool_result(prefix)
                if result:
                    data = result.get("data", {})
                    # Special case: "${step_X.result}" returns full data as JSON
                    if rest == "result":
                        if isinstance(data, dict) and data:
                            return json.dumps(data)
                        return str(data)
                    # Try nested access into data
                    val = _get_nested(data, rest)
                    if val is not None:
                        return str(val)
                    # If nested path fails (e.g. "result.longitude" but data has "results[0].longitude"),
                    # return the full data JSON so the LLM can retry with proper field names
                    if isinstance(data, dict) and data:
                        return json.dumps(data)

        # Try bare prefix as tool name (get full result data)
        result = _find_tool_result(key)
        if result:
            data = result.get("data", {})
            if isinstance(data, dict) and data:
                return json.dumps(data)
            return str(data)

        return f"<<unresolved:{key}>>"

    def _resolve_value(val: Any) -> Any:
        """Recursively resolve placeholders at ANY nesting depth (dicts, lists, strings)."""
        if isinstance(val, str):
            return _PLACEHOLDER_RE.sub(_replacer, val)
        if isinstance(val, dict):
            return {k: _resolve_value(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_resolve_value(item) for item in val]
        return val

    return {k: _resolve_value(v) for k, v in raw_inputs.items()}


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

    if isinstance(step.get("tool_name"), str) and step["tool_name"].lower() in ("null", "none", ""):
        step["tool_name"] = None
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
    retry_count: int = 0  # track consecutive retries to prevent infinite loops
    messages: list[dict[str, Any]] = list(state.get("messages", []))
    new_messages: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = list(state.get("tool_results", []))
    errors: list[str] = list(state.get("errors", []))

    tool_desc_list = [{"name": t["name"], "description": t.get("description", "")} for t in tools]
    tool_descriptions = json.dumps(tool_desc_list, indent=2) if tool_desc_list else "No tools available."

    example_context = {
        "response_type": "tool",
        "intent": (state.get("intent") or {}).get("intent", ""),
    }
    system_content = prompt_manager.render_with_examples(
        "execute_step",
        version="2.0",
        context=example_context,
        max_examples=3,
        max_mistakes=3,
        tool_descriptions=tool_descriptions,
        additional_context="",
    )

    # Inject relevant long-term memories into system prompt
    try:
        from nexus.memory.manager import MemoryManager  # noqa: PLC0415
        from nexus.memory.store import MemoryStore  # noqa: PLC0415
        memory_manager = MemoryManager(store=MemoryStore(), llm=llm)
        step_description = step.get("description", "")
        memory_context = await memory_manager.retrieve_formatted(query=step_description)
        if memory_context:
            system_content = memory_context + "\n\n" + system_content
            logger.info("memory.injected_into_execute_step", context_len=len(memory_context))
    except Exception:
        logger.warning("memory.injection_failed", exc_info=True)

    # Resolve placeholders in step inputs
    gathered: dict[str, Any] = state.get("gathered_requirements", {})
    user_context: dict[str, Any] = state.get("user_context", {})
    plan_steps: list[dict[str, Any]] = list(state.get("plan") or [])
    step_inputs_raw: dict[str, Any] = step.get("inputs") or {}
    step_inputs = _resolve_placeholders(step_inputs_raw, gathered, tool_results, user_context, plan_steps)

    # Auto-map resolved JSON values to schema fields
    tool_name = step.get("tool_name")
    if tool_name and tool_name in tool_map:
        schema = tool_map[tool_name].get("input_schema", {})
        required = schema.get("required", [])
        if required:
            for field in required:
                if field not in step_inputs or not step_inputs.get(field):
                    for k, v in list(step_inputs.items()):
                        if isinstance(v, str):
                            try:
                                parsed = json.loads(v)
                                if isinstance(parsed, dict):
                                    # Try to extract the required field from nested data
                                    if field in parsed:
                                        step_inputs[field] = parsed[field]
                                    # Also check for results array (geocoding API format)
                                    results_list = parsed.get("results") or parsed.get("data", {}).get("results") or []
                                    if isinstance(results_list, list) and results_list:
                                        for item in results_list:
                                            if isinstance(item, dict) and field in item:
                                                step_inputs[field] = item[field]
                                                break
                            except (json.JSONDecodeError, TypeError):
                                pass

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

    while sub_iterations < settings.max_sub_iterations:
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

                # Override LLM's arguments with resolved step_inputs when they contain placeholders
                # This ensures correct field values even when the LLM re-uses plan placeholders
                for arg_key, arg_val in list(func_args.items()):
                    if isinstance(arg_val, str) and ("${" in arg_val or "<<unresolved:" in arg_val):
                        if arg_key in step_inputs:
                            func_args[arg_key] = step_inputs[arg_key]
                        elif arg_key == "coordinates" and "latitude" in step_inputs:
                            # Special case: LLM uses "coordinates" but schema needs lat/lon
                            func_args["latitude"] = step_inputs.get("latitude")
                            func_args["longitude"] = step_inputs.get("longitude")
                            func_args.pop("coordinates", None)

                # Validate resolved inputs before execution (1 correction retry)
                input_schema = tool_def.get("input_schema")
                validation_error = _validate_inputs(func_args, input_schema)
                if validation_error:
                    correction_prompt = prompt_manager.render_with_examples(
                        "execute_step_correction",
                        context={"response_type": "tool", "intent": f"correct_{func_name}"},
                        max_examples=2,
                        max_mistakes=2,
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
                        # Check if unresolved placeholders are the cause
                        raw_str = json.dumps(func_args)
                        if "<<unresolved:" in raw_str:
                            err_msg = f"Input placeholder could not be resolved for '{func_name}'. The plan needs revision: the step references results that don't exist or have wrong field names."
                        else:
                            err_msg = f"Input validation failed for '{func_name}': {validation_error}"
                        errors.append(err_msg)
                        step["status"] = "failed"
                        plan_list = list(state.get("plan") or [])
                        plan_list[state["current_step_index"]] = step
                        return {
                            "plan": plan_list,
                            "tool_results": tool_results,
                            "errors": errors,
                            "_routing_decision": "revise",
                        }

                if event_bus:
                    await event_bus.publish(
                        agent_channel(state["session_id"]),
                        {"type": "tool_call_started", "tool_name": func_name, "inputs": func_args},
                    )

                tool_read = ToolRead(**tool_def)
                ctx = ExecutionContext(
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
                    recovery_prompt = prompt_manager.render_with_examples(
                        "execute_step_error_recovery",
                        context={"response_type": "tool", "intent": f"recover_{func_name}"},
                        max_examples=2,
                        max_mistakes=2,
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
                            retry_count += 1
                            if retry_count >= 3:
                                # Too many retries — escalate to revise
                                errors.append(f"Tool '{func_name}' failed after {retry_count} retries")
                                step["status"] = "failed"
                                plan_list = list(state.get("plan") or [])
                                plan_list[state["current_step_index"]] = step
                                result_dict = result.model_dump(mode="json")
                                tool_results.append(result_dict)
                                return {
                                    "plan": plan_list,
                                    "tool_results": tool_results,
                                    "errors": errors,
                                    "scratchpad": state.get("scratchpad", ""),
                                    "iteration_count": state.get("iteration_count", 0) + 1,
                                    "_routing_decision": "revise",
                                    "pending_approval": None,
                                }
                            modified = recovery.get("modified_inputs", func_args)
                            func_args = modified
                            continue  # retry the current iteration
                        if recovery_action == "revise":
                            step["status"] = "failed"
                            plan_list = list(state.get("plan") or [])
                            plan_list[state["current_step_index"]] = step
                            result_dict = result.model_dump(mode="json")
                            tool_results.append(result_dict)
                            return {
                                "plan": plan_list,
                                "tool_results": tool_results,
                                "errors": errors,
                                "scratchpad": state.get("scratchpad", ""),
                                "iteration_count": state.get("iteration_count", 0) + 1,
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
                new_messages.append(current_messages[-2])
                new_messages.append(current_messages[-1])

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
            new_messages.append(messages[-1])
            break

    step["status"] = "done" if not errors else "failed"
    plan_list = list(state.get("plan") or [])
    plan_list[state["current_step_index"]] = step

    scratchpad: str = state.get("scratchpad", "")
    scratchpad += f"\n--- Step {state['current_step_index']} ---\n"
    scratchpad += json.dumps(tool_results[-1] if tool_results else {"note": step["status"]})

    return {
        "messages": new_messages,
        "plan": plan_list,
        "tool_results": tool_results,
        "errors": errors,
        "scratchpad": scratchpad,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "_routing_decision": "continue",
    }
