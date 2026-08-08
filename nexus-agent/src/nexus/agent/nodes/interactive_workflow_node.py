"""InteractiveWorkflowNode — manages multi-turn dynamic workflows as DAGs."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import structlog

from nexus.agent.node_wrapper import context_node
from nexus.agent.router import QueryType
from nexus.capabilities.template_engine import WorkflowTemplateEngine
from nexus.compiler.ir_models import LogicalNode, LogicalWorkflow
from nexus.context.global_context import get_global_context
from nexus.execution.context import ExecutionContext, StatePatch
from nexus.llm.client import LLMClient

logger = structlog.get_logger("nexus.agent.nodes.interactive_workflow")


def _is_numeric(value: str) -> bool:
    """True when a string is a plain number (lat/lon-like)."""
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


async def _resolve_step_artifacts(
    step_intent: str,
    resolved_inputs: dict[str, Any],
    step_ref: str,
    gc: Any,
) -> tuple[dict[str, Any], list[LogicalNode]]:
    """Metadata-driven artifact resolution for workflow steps.

    When a step's inputs contain PLACE-LIKE text (non-numeric strings) for
    artifacts the target capability CONSUMES (e.g. a city name where
    ``latitude``/``longitude`` are required), the registry is searched for a
    capability that PRODUCES those artifacts and ACCEPTS the provided value
    (its input schema's ``x-aliases`` contain the value's key, or the value
    key matches its consumed artifacts). That producer is PREPENDED as a
    chained step — the compiler's static dataflow wires output → input, so
    the workflow transparently resolves "Tokyo" into coordinates before the
    weather tool runs.

    Fully metadata-driven: capability names, artifacts, and aliases come
    from the registry — no hardcoded tools.
    """
    meta = (gc.capability_index or {}).get(step_intent) or {}
    consumes = set(meta.get("consumes") or [])
    if not consumes:
        return resolved_inputs, []

    # Place-like values: non-numeric strings provided for a consumed artifact.
    place_values = {
        k: str(v)
        for k, v in resolved_inputs.items()
        if isinstance(v, str) and v.strip() and not _is_numeric(v.strip())
    }
    if not place_values:
        return resolved_inputs, []

    producers: list[tuple[str, set[str], int]] = []  # (name, overlap, alias_score)
    for name, m in (gc.capability_index or {}).items():
        if name == step_intent or not m.get("produces"):
            continue
        overlap = set(m["produces"]) & consumes
        if not overlap:
            continue
        alias_score = 0
        schema = m.get("input_schema") or {}
        props = schema.get("properties") if isinstance(schema, dict) else None
        for key in place_values:
            if key in set(m.get("consumes") or []):
                alias_score += 2
            if isinstance(props, dict):
                for pname, pdef in props.items():
                    if isinstance(pdef, dict) and key in (pdef.get("x-aliases") or []):
                        alias_score += 1
        producers.append((name, overlap, alias_score))

    if not producers:
        return resolved_inputs, []
    # Best producer: most overlap first, then alias compatibility, then name.
    producers.sort(key=lambda p: (len(p[1]), p[2]), reverse=True)
    producer_name, overlap, _ = producers[0]

    producer_meta = (gc.capability_index or {}).get(producer_name) or {}
    producer_schema = producer_meta.get("input_schema") or {}
    producer_props = producer_schema.get("properties") if isinstance(producer_schema, dict) else {}

    # Map the place value into the producer's parameter: prefer an exact key
    # that matches a producer prop (or alias); fall back to the first prop.
    first_place_key = next(iter(place_values))
    first_place_value = place_values[first_place_key]
    producer_input: dict[str, Any] = {}
    if isinstance(producer_props, dict) and producer_props:
        chosen = first_place_key if first_place_key in producer_props else None
        if chosen is None:
            for pname, pdef in producer_props.items():
                if isinstance(pdef, dict) and first_place_key in (pdef.get("x-aliases") or []):
                    chosen = pname
                    break
        if chosen is None:
            chosen = next(iter(producer_props))
        producer_input[chosen] = first_place_value

    producer_ref = f"{step_ref}_coords"
    producer_node = LogicalNode(
        op=producer_name,
        ref=producer_ref,
        inputs=producer_input,
        depends_on=[],
    )

    # Rewrite the target step's inputs: missing consumed artifacts are pulled
    # from the producer's result (compiler static-dataflow wiring). The FIELD
    # used is metadata-driven: the artifact name first, then the consumer's
    # input-schema x-aliases that the producer's declared outputs contain
    # (e.g. artifact "latitude" ← producer field "lat").
    target_schema = (meta.get("input_schema") or {})
    target_props = target_schema.get("properties") if isinstance(target_schema, dict) else {}
    producer_outputs = set(producer_meta.get("produces") or [])

    def _field_for(artifact: str) -> str:
        aliases = [artifact]
        prop = target_props.get(artifact) if isinstance(target_props, dict) else None
        if isinstance(prop, dict):
            aliases += [str(a) for a in (prop.get("x-aliases") or []) if isinstance(a, str)]
        for alias in aliases:
            if alias in producer_outputs:
                return alias
        return artifact

    rewritten = {
        k: v
        for k, v in resolved_inputs.items()
        if k not in place_values
    }
    for artifact in sorted(overlap):
        if artifact not in rewritten or not isinstance(rewritten.get(artifact), str):
            rewritten[artifact] = f"${{{producer_ref}.result.{_field_for(artifact)}}}"

    logger.info(
        "interactive_workflow.artifact_resolved",
        step=step_ref,
        target=step_intent,
        producer=producer_name,
        artifacts=sorted(overlap),
        place=first_place_value[:40],
    )
    return rewritten, [producer_node]


@context_node
async def interactive_workflow_node(ctx: ExecutionContext, llm: LLMClient, model: str) -> StatePatch:
    """Manages multi-turn interactive workflows dynamically as DAGs."""
    snapshot = ctx.snapshot
    active_wf = snapshot.get("_active_workflow_id")
    updates = {}

    # --- 1. Initialize Workflow ---
    if not active_wf:
        intent_data = snapshot.get("intent", {})
        intent_str = ""
        if isinstance(intent_data, dict):
            q_type = intent_data.get("query_type", "")
            if q_type == QueryType.WORKFLOW.value:
                intent_str = _last_user_message(snapshot)
            else:
                intent_str = intent_data.get("intent", "") or _last_user_message(snapshot)

        if not intent_str:
            return StatePatch(version=ctx.version + 1, updates={})

        engine = WorkflowTemplateEngine(llm=llm)
        gc = get_global_context()
        available_caps = list(gc.capability_providers.keys())

        workflow_def = await engine.compose_workflow(
            intent=intent_str,
            available_capabilities=available_caps,
            user_context=snapshot.get("user_context", {}),
        )

        if not workflow_def or not workflow_def.get("steps"):
            return StatePatch(version=ctx.version + 1, updates={})

        active_wf = str(uuid.uuid4())
        updates.update({
            "_active_workflow_id": active_wf,
            "_workflow_type": workflow_def.get("name", "generic_workflow"),
            "_workflow_definition": workflow_def,
            "_workflow_steps_total": len(workflow_def["steps"]),
            "_workflow_completed_steps": [],
        })

        # CRITICAL: Dynamic Intent Pre-Population
        # Extract all possible variables from the initial message to skip
        # unnecessary questions when the user provides everything up front.
        collected = await _pre_populate_slots_from_intent(
            llm, model, intent_str, workflow_def.get("steps", [])
        )

        captured = set()
        is_first_turn = True

    else:
        workflow_def = snapshot.get("_workflow_definition", {})
        # IMMUTABLE: always copy before writing — `_workflow_collected` is a
        # shared reference into the checkpointed channel; mutating it in place
        # violates Context(v) immutability and can leak into a retried node.
        collected = dict(snapshot.get("_workflow_collected", {}))
        captured = set(snapshot.get("_workflow_captured", []))
        is_first_turn = False

        # HYBRID RESUME: a dynamic step was routed to the SemanticPlanner on
        # the previous graph pass; its artifacts are now in the ArtifactGraph.
        # Capture them into the pending step so it is marked executed and the
        # workflow can continue to the next step.
        pending_dynamic = snapshot.get("_workflow_dynamic_pending")
        if pending_dynamic:
            try:
                from nexus.artifacts.graph import get_artifact_graph
                from nexus.compiler.context_ir import _deep_unfreeze
                artifacts = get_artifact_graph(str(snapshot.get("session_id", ""))).all()
                new_artifacts = [a for a in artifacts if a.execution_id not in captured]
                if new_artifacts:
                    collected[pending_dynamic] = [
                        _deep_unfreeze(a.data) for a in new_artifacts
                    ]
                    captured.add(pending_dynamic)
                    updates["_workflow_dynamic_pending"] = None
                    updates["_workflow_dynamic_intent"] = None
                    logger.info(
                        "interactive_workflow.dynamic_captured",
                        step=pending_dynamic,
                        artifacts=len(new_artifacts),
                    )
                else:
                    # No artifact yet — keep the pending marker so a later
                    # pass (or response node) can still capture results.
                    logger.info(
                        "interactive_workflow.dynamic_pending_no_artifact",
                        step=pending_dynamic,
                    )
            except Exception as exc:
                logger.warning(
                    "interactive_workflow.dynamic_capture_failed",
                    step=pending_dynamic,
                    error=str(exc),
                )

        # Capture previous step's tool results from the ArtifactGraph dynamically
        try:
            from nexus.artifacts.graph import get_artifact_graph
            from nexus.compiler.context_ir import _deep_unfreeze
            artifacts = get_artifact_graph(str(snapshot.get("session_id", ""))).all()
            if artifacts:
                for art in artifacts:
                    cap_id = getattr(art, "capability_id", "") or ""
                    tool_name = getattr(art, "tool_name", "") or ""
                    for step in workflow_def.get("steps", []):
                        step_intent = step.get("intent") or step.get("capability")
                        if step_intent == cap_id or step_intent == tool_name:
                            # The step's tool result is present in the graph.
                            # If its id is already in `collected` (e.g. the slot
                            # holds the USER INPUT for an input step), do not
                            # overwrite it — but DO mark it captured so the
                            # step is considered executed.
                            if step.get("id") not in collected:
                                collected[step["id"]] = _deep_unfreeze(art.data)
                            captured.add(step["id"])
                            logger.info(
                                "interactive_workflow.result_captured",
                                step=step["id"],
                                tool=tool_name,
                            )
                            break
        except Exception as exc:
            logger.warning("interactive_workflow.result_capture_failed", error=str(exc))

    steps = workflow_def.get("steps", [])
    user_msg = _last_user_message(snapshot)

    def _step_done(step: dict) -> bool:
        """A step is done when its input is collected AND its execution is
        satisfied: either it has no tool inputs (pure question step) or its
        tool result has been captured. Steps blocked by approval stay pending
        because their result is not yet in ``collected``/``captured``."""
        step_id = step["id"]
        if step.get("requires_input", False) and step_id not in collected:
            return False
        has_execution = bool(step.get("inputs"))
        if has_execution:
            return step_id in captured
        return True

    # --- 2. Identify if we are waiting for user input ---
    pending_input_step = None
    for step in steps:
        if _step_done(step):
            continue
        if step.get("requires_input", False) and step["id"] not in collected:
            pending_input_step = step
            break

    # --- 3. Process user input if we were waiting for it ---
    if pending_input_step and not is_first_turn:
        logger.info(
            "interactive_workflow.pending_input",
            step=pending_input_step["id"],
            msg=user_msg[:60],
        )
        intent = await _classify_user_intent(llm, model, user_msg, pending_input_step)
        if intent == "cancel":
            updates.update({
                "_active_workflow_id": None,
                "final_response": "Workflow cancelled. How can I help you next?",
                "_routing_decision": "finalize",
                "response_type": "cancellation",
            })
            return StatePatch(version=ctx.version + 1, updates=updates)
        elif intent == "off_topic":
            updates.update({
                "_bypass_workflow": True,
                "_route_to_router": True,
            })
            return StatePatch(version=ctx.version + 1, updates=updates)
        else:
            slot_value = await _extract_slot_value_llm(llm, model, user_msg, pending_input_step)
            if slot_value is not None:
                collected[pending_input_step["id"]] = slot_value
                pending_input_step = None
            else:
                question = pending_input_step.get("question", "Please provide input for this step.")
                updates.update({
                    "final_response": question,
                    "_routing_decision": "finalize",
                    "response_type": "clarification",
                })
                return StatePatch(version=ctx.version + 1, updates=updates)

    # --- 3b. Workflow blocked mid-execution (e.g. approval pending) but the
    # user sent a new message that is NOT an answer to a pending question.
    # Classify it first: cancel / off-topic must not be absorbed into the
    # workflow's approval loop (previously every new message re-requested
    # the same approval instead of routing off-topic questions away).
    elif not is_first_turn and any(not _step_done(s) for s in steps):
        pending_step = pending_input_step or next(
            (s for s in steps if not _step_done(s)), None
        )
        intent = await _classify_user_intent(llm, model, user_msg, pending_step or {})
        if intent == "cancel":
            updates.update({
                "_active_workflow_id": None,
                "final_response": "Workflow cancelled. How can I help you next?",
                "_routing_decision": "finalize",
                "response_type": "cancellation",
            })
            return StatePatch(version=ctx.version + 1, updates=updates)
        if intent == "off_topic":
            updates.update({
                "_bypass_workflow": True,
                "_route_to_router": True,
            })
            return StatePatch(version=ctx.version + 1, updates=updates)
        # "answer" intent → fall through to the normal DAG planning below;
        # a blocked step will simply re-request approval (correct for
        # explicit continuation).

    # --- 4. Dynamic DAG Planning ---
    logical_nodes = []
    steps_executed_this_turn = []
    missing_input_step = None

    gc = get_global_context()
    # Valid capabilities = compiled-graph providers ∪ the full capability
    # index (registered tools are indexed there; providers only cover the
    # compiled graph). One universe — no hardcoded names.
    valid_caps = set(gc.capability_providers.keys()) | set((gc.capability_index or {}).keys())
    if gc.compiled_graph:
        for node in gc.compiled_graph.nodes.values():
            lop = getattr(node, "logical_op_name", "") or ""
            if lop:
                valid_caps.add(lop)

    for step in steps:
        step_id = step["id"]

        if _step_done(step):
            continue

        # HYBRID: a step declared ``dynamic: true`` has no fixed capability —
        # its execution plan is produced by the SemanticPlanner at runtime
        # using the step's own intent description. Route there and resume.
        if step.get("dynamic") is True or step.get("dynamic") == "true":
            dynamic_intent = (
                step.get("intent")
                or step.get("description")
                or step.get("question")
                or step_id
            )
            updates.update({
                "_workflow_collected": collected,
                "_workflow_captured": sorted(captured),
                "_workflow_dynamic_pending": step_id,
                "_workflow_dynamic_intent": dynamic_intent,
                "_route_to_planner": True,
                "_bypass_workflow": True,
            })
            logger.info(
                "interactive_workflow.dynamic_step",
                step=step_id,
                intent=dynamic_intent,
            )
            return StatePatch(version=ctx.version + 1, updates=updates)

        # Check if user input is required and missing
        if step.get("requires_input", False) and step_id not in collected:
            missing_input_step = step
            break

        # CRITICAL: A placeholder is unresolved only if the referenced variable
        # is not yet in `collected` — NOT merely because the ${...} pattern exists
        step_inputs = step.get("inputs", {})
        if not isinstance(step_inputs, dict):
            step_inputs = {}
        if _has_unresolved_placeholders(step_inputs, collected):
            break

        resolved_inputs = _resolve_workflow_variables(step_inputs, collected)

        step_intent = step.get("intent") or step.get("capability")
        if step_intent not in valid_caps:
            logger.error("interactive_workflow.invalid_capability", capability=step_intent)
            updates.update({
                "_active_workflow_id": None,
                "final_response": f"Workflow failed: Step capability '{step_intent}' is not registered.",
                "_routing_decision": "finalize",
                "response_type": "error",
            })
            return StatePatch(version=ctx.version + 1, updates=updates)

        # Metadata-driven artifact resolution: place-like inputs for consumed
        # artifacts (e.g. "Tokyo" → latitude/longitude) are resolved through a
        # registered producer capability, prepended as a chained step.
        resolved_inputs, producer_nodes = await _resolve_step_artifacts(
            step_intent, resolved_inputs, step_id, gc,
        )
        logical_nodes.extend(producer_nodes)

        logical_nodes.append(LogicalNode(
            op=step_intent,
            ref=step_id,
            inputs=resolved_inputs,
            depends_on=[n.ref for n in producer_nodes],
        ))

    # --- 5. Execution Decision ---
    done_ids = [s["id"] for s in steps if _step_done(s)]
    if logical_nodes:
        logical_workflow = LogicalWorkflow(nodes=logical_nodes, collections={})

        updates.update({
            "_workflow_collected": collected,
            "_workflow_captured": sorted(captured),
            "_logical_workflow": logical_workflow.model_dump(),
            "_workflow_next_action": "execute_step",
            "_route_to_compiler": True,
        })
        return StatePatch(version=ctx.version + 1, updates=updates)

    elif missing_input_step:
        question = missing_input_step.get("question", "Please provide input for this step.")
        updates.update({
            "final_response": question,
            "_routing_decision": "finalize",
            "response_type": "clarification",
            "_workflow_collected": collected,
            "_workflow_captured": sorted(captured),
        })
        return StatePatch(version=ctx.version + 1, updates=updates)

    else:
        if len(done_ids) == len(steps):
            payload = {
                "workflow_type": updates.get("_workflow_type", snapshot.get("_workflow_type", "")),
                "collected": collected,
                "steps_completed": done_ids,
            }
            updates.update({
                "_workflow_next_action": "finalize",
                "_active_workflow_id": None,
                "_structured_payload": payload,
                "_routing_decision": "finalize",
                "response_type": "artifact",
            })
            return StatePatch(version=ctx.version + 1, updates=updates)
        else:
            logger.error(
                "interactive_workflow.stuck",
                done=done_ids,
                total=len(steps),
                collected_keys=list(collected.keys()),
                captured=sorted(captured),
                definition_steps=len(workflow_def.get("steps", [])),
            )
            updates.update({
                "_active_workflow_id": None,
                "final_response": "Workflow is stuck or missing dependencies.",
                "_routing_decision": "finalize",
                "response_type": "error",
            })
            return StatePatch(version=ctx.version + 1, updates=updates)


def _has_unresolved_placeholders(inputs: dict, collected: dict) -> bool:
    """Return True if any input references a variable not yet in ``collected``.

    A placeholder like ``${step_1}`` or ``${step_1.results}`` is resolved once
    the referenced step id exists in ``collected`` — regardless of whether the
    raw ``${...}`` pattern is still present in the template.
    """
    placeholder_re = re.compile(r"\$\{([^}]+)\}")
    for v in inputs.values():
        if isinstance(v, str):
            for m in placeholder_re.finditer(v):
                var_name = m.group(1).split(".")[0]
                if var_name not in collected:
                    return True
    return False


async def _pre_populate_slots_from_intent(
    llm: LLMClient,
    model: str,
    user_msg: str,
    steps: list[dict],
) -> dict:
    """Dynamically extract all possible slot values from the initial user message.

    Used on workflow initialization so that a user who provides all context
    up front (e.g. "…using the first datasource and the second table") does
    not get asked redundant questions.

    Returns a dict keyed by step id containing only non-null extracted values.
    Returns ``{}`` on failure or when no input steps exist.
    """
    if not user_msg or not steps:
        return {}

    required_inputs: dict[str, str] = {}
    for step in steps:
        if step.get("requires_input", False):
            required_inputs[step["id"]] = step.get("question", step.get("description", ""))

    if not required_inputs:
        return {}

    system_prompt = (
        "You are an intent extraction AI. The user wants to start a workflow. "
        "Extract the values for the required steps from the user's message. "
        "If a value is not present in the message, use null for that key. "
        "Return ONLY a valid JSON object mapping step IDs to extracted values."
    )

    user_prompt = (
        f"User Message: {user_msg}\n"
        f"Required Steps: {json.dumps(required_inputs, indent=2)}\n"
        'Example Output: {"step_1": "<extracted_value>", "step_2": null}'
    )

    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=100,
        )
        if response.failed:
            raise RuntimeError(response.error)
        content = response.content.strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            extracted = {k: v for k, v in data.items() if v is not None}
            # FRAGMENT GUARD (deterministic, language-agnostic): a real
            # slot value extracted from a message is a FRAGMENT of it —
            # "Tokyo" inside "I need a weather briefing for Tokyo". An
            # extraction that echoes the whole message (or most of it) is
            # the model failing to find a value ("I need a weather
            # briefing" → value "I need a weather briefing"), which would
            # silently execute the workflow with garbage input. Discard
            # such values so the workflow asks its question instead.
            msg_len = max(1, len(user_msg.strip()))
            extracted = {
                k: v
                for k, v in extracted.items()
                if isinstance(v, str) and v.strip()
                and v.strip() != user_msg.strip()
                and len(v.strip()) < max(10, msg_len * 0.5)
            }
            if extracted:
                return extracted
    except Exception as exc:
        logger.warning("interactive_workflow.pre_populate_failed", error=str(exc))

    # Structural fallback (no word lists): map snake_case/kebab-case/dotted
    # tokens from the message to input steps in order of appearance. This is a
    # language-agnostic pattern — quoted values or code-like identifiers.
    tokens = []
    for m in re.finditer(r"[\"']([^\"']+)[\"']|\b[a-zA-Z][a-zA-Z0-9_-]*(?:_[a-zA-Z0-9_-]+)+\b", user_msg):
        token = m.group(1) or m.group(0)
        if token not in tokens:
            tokens.append(token)

    if tokens:
        input_steps = [s["id"] for s in steps if s.get("requires_input", False)]
        structural: dict[str, Any] = {}
        for idx, step_id in enumerate(input_steps):
            if idx < len(tokens):
                structural[step_id] = tokens[idx]
        if structural:
            logger.info(
                "interactive_workflow.pre_populated_structural",
                slots=list(structural.keys()),
            )
            return structural

    return {}


async def _classify_user_intent(llm: LLMClient, model: str, user_msg: str, step_def: dict) -> str:
    """Dynamically classify if the user is answering, cancelling, or off-topic."""
    if not user_msg:
        return "answer"

    system_prompt = (
        "You are an intent classification AI. Analyze the user's message in the context of the current workflow step. "
        "Classify the intent into exactly one of these categories:\n"
        "- 'answer': The user is providing the requested input or responding to the question.\n"
        "- 'cancel': The user wants to stop, cancel, or abort the current workflow.\n"
        "- 'off_topic': The user is asking a completely different question or changing the subject.\n\n"
        'Respond with ONLY a valid JSON object in this exact format: {"intent": "<category>"}'
    )

    user_prompt = (
        f"Current step question: {step_def.get('question', 'No specific question')}\n"
        f"User message: {user_msg}"
    )

    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=50,
        )
        if response.failed:
            raise RuntimeError(response.error)
        content = response.content.strip()

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            intent = data.get("intent", "answer").lower()
            if intent in ["answer", "cancel", "off_topic"]:
                return intent

        return "answer"

    except Exception as exc:
        logger.warning("interactive_workflow.intent_classification_failed", error=str(exc))
        return "answer"


async def _extract_slot_value_llm(llm: LLMClient, model: str, user_msg: str, step_def: dict) -> Any:
    """Dynamically extract the slot value from user input using a fast LLM call."""
    if not user_msg:
        return None

    # Structural fast-path (no word lists — pure regex on syntax):
    # quoted values and snake_case/kebab-case identifiers
    structural = _structural_slot_extract(user_msg)
    if structural is not None:
        return structural

    # BARE-ENTITY fast-path (deterministic): a short answer to a pending
    # slot question IS the value ("Tokyo", "31.5, 74.3", "Acme Inc") —
    # there is nothing to extract. This also sidesteps extraction-LLM
    # flakiness (the model occasionally echoes its own instruction instead
    # of the value). Long messages still go through the LLM (the value is
    # a fragment of a sentence).
    if len(user_msg.strip()) <= 25:
        return user_msg.strip()

    expected = step_def.get("expected_input", {})
    schema_str = json.dumps(expected) if expected else (
        "No specific schema provided. Extract the core entity value the user provides."
    )

    system_prompt = (
        "You are a data extraction assistant. Your task is to extract the core value from the user's message. "
        "Respond with ONLY the extracted value as a string (e.g., 'value_one'). "
        "If the user's message is conversational but contains the value, extract just the value. "
        "If no value is found, respond with exactly 'None'."
    )

    user_prompt = (
        f"User Message: {user_msg}\n"
        f"Expected Input: {schema_str}"
    )

    try:
        response = await llm.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=50,
        )
        if response.failed:
            raise RuntimeError(response.error)
        val = response.content.strip()

        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]

        if val.lower() == "none" or not val:
            return None
        # FRAGMENT GUARD (deterministic, language-agnostic): a real slot
        # value is a FRAGMENT of the message ("Tokyo" inside "It's Tokyo").
        # An extraction that echoes the message — or the extraction
        # instruction itself (observed: the model returned "We need to
        # extract core value from user...") — is a failed extraction and
        # must be rejected so the workflow re-asks instead of executing
        # with garbage input.
        msg = user_msg.strip()
        if val.strip() == msg or len(val.strip()) >= max(10, len(msg) * 0.5):
            logger.warning(
                "interactive_workflow.slot_extraction_degenerate",
                value=val[:60],
            )
            return None
        return val
    except Exception as exc:
        logger.warning("interactive_workflow.slot_extraction_failed", error=str(exc))
        # Dynamic fallback: return the raw message so the workflow never deadlocks
        # re-asking the same question on every turn
        return user_msg.strip()


def _structural_slot_extract(user_msg: str) -> Any:
    """Deterministic, syntax-only slot extraction — no domain word lists.

    Matches quoted values or snake_case/kebab-case identifiers, which are
    language-agnostic structural patterns (not hardcoded domain keywords).
    Returns None when no structural token is present.
    """
    text = user_msg.strip()
    if not text:
        return None

    m = re.search(r"[\"']([^\"']+)[\"']", text)
    if m:
        return m.group(1).strip()

    m = re.search(r"\b[a-zA-Z][a-zA-Z0-9_-]*(?:_[a-zA-Z0-9_-]+)+\b", text)
    if m:
        return m.group(0)

    return None


def _resolve_workflow_variables(inputs: dict, collected: dict) -> dict:
    """Replaces ${var} or ${var.path} placeholders in inputs with collected workflow values."""
    def _resolve_path(path: str, data: Any) -> Any:
        if data is None:
            return None
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                if idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                return None
        return current

    def replacer(match: re.Match) -> str:
        path = match.group(1)
        parts = path.split(".")
        var_name = parts[0]
        var_path = ".".join(parts[1:]) if len(parts) > 1 else ""

        val = collected.get(var_name)
        if var_path:
            val = _resolve_path(var_path, val)

        if val is None:
            return ""

        return str(val)

    resolved = {}
    for k, v in inputs.items():
        if isinstance(v, str):
            full_match = re.fullmatch(r"\$\{([a-zA-Z0-9_.]+)\}", v.strip())
            if full_match:
                path = full_match.group(1)
                parts = path.split(".")
                var_name = parts[0]
                var_path = ".".join(parts[1:]) if len(parts) > 1 else ""
                val = collected.get(var_name)
                if var_path:
                    val = _resolve_path(var_path, val)
                resolved[k] = val
            else:
                resolved[k] = re.sub(r"\$\{([a-zA-Z0-9_.]+)\}", replacer, v)
        else:
            resolved[k] = v
    return resolved


def _last_user_message(state: dict) -> str:
    messages = state.get("messages", [])
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            return str(m.get("content", ""))
    return ""
