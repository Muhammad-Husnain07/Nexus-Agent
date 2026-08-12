"""Node Contract Registry — the single source of truth for orchestration
node responsibilities.

Every graph node declares: its phase (compile / runtime / routing), the
state fields it READS and WRITES (single ownership), typed outputs/inputs,
failure modes, skip conditions, recovery path, and who consumes its outputs.
``tests/test_node_contracts.py`` statically verifies the registry against
the implementation (AST writer extraction + consistency checks) — drift
fails CI before it can corrupt behavior.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field


class NodePhase(str, Enum):
    """Orchestration phase — compile nodes never write runtime fields."""

    COMPILE = "compile"    # planning, validation, compilation, optimization
    RUNTIME = "runtime"    # execution, recovery, synthesis, memory
    ROUTING = "routing"    # classification + conversational resume


class NodeContract(BaseModel):
    """Immutable contract a graph node must satisfy."""

    model_config = ConfigDict(frozen=True)

    node_id: str = Field(description="Graph node id (must match graph.py add_node)")
    phase: NodePhase = Field(description="compile | runtime | routing")
    module: str = Field(description="Module path scanned by the drift test")
    func_name: str = Field(default="", description="Node function to scan (empty = whole module)")
    inputs: tuple[str, ...] = Field(default=(), description="State fields consumed")
    reads: tuple[str, ...] = Field(default=(), description="External reads (artifact graph, registry, DB)")
    writes: tuple[str, ...] = Field(default=(), description="State fields OWNED (single owner)")
    produces: tuple[str, ...] = Field(default=(), description="Typed outputs")
    consumes: tuple[str, ...] = Field(default=(), description="Typed inputs")
    may_fail: bool = Field(default=True, description="Can this node fail?")
    skip_if: str = Field(default="", description="Documented skip condition")
    recovery: str = Field(default="", description="Documented recovery path")
    output_consumed_by: tuple[str, ...] = Field(default=(), description="Node ids consuming the outputs")


NODE_CONTRACTS: Final[tuple[NodeContract, ...]] = (
    NodeContract(
        node_id="RouterNode", phase=NodePhase.ROUTING,
        module="nexus.agent.router",
        inputs=("messages",),
        reads=("GlobalContext", "ResolutionEngine"),
        writes=("_query_type", "_goals", "_needs_requirements", "_preferred_tools",
                "_domain_hint", "intent", "response_type", "_invocation_budget"),
        produces=("routing_decision",),
        consumes=("user_message",),
        may_fail=True,
        skip_if="",
        recovery="LLM classifier fallback → heuristic default",
        output_consumed_by=("SemanticPlannerNode", "ResponseNode", "RequirementCollectorNode",
                            "InteractiveWorkflowNode", "ApprovalCheckpointResumeNode"),
    ),
    NodeContract(
        node_id="SemanticPlannerNode", phase=NodePhase.COMPILE,
        module="nexus.agent.nodes.semantic_parser_node",
        inputs=("messages", "_domain_hint", "_preferred_tools", "_replan_context",
                "_plan_validator_errors"),
        reads=("GlobalContext", "ResolutionEngine", "MemoryScout", "registry"),
        writes=("_logical_workflow", "_extraction_result", "_budget_exceeded", "errors",
                "_total_tokens", "_cost_breakdown", "total_cost_usd",
                "_invocation_budget", "_binding_report", "_detected_intents"),
        produces=("LogicalWorkflow",),
        consumes=("user_message", "capability_catalog"),
        may_fail=True,
        skip_if="",
        recovery="3-attempt extraction retry → error patch",
        output_consumed_by=("PlanValidatorNode",),
    ),
    NodeContract(
        node_id="PlanValidatorNode", phase=NodePhase.COMPILE,
        module="nexus.agent.nodes.plan_validator_node",
        inputs=("_logical_workflow", "_execution_graph", "_detected_intents"),
        reads=("GlobalContext",),
        writes=("_plan_validator_report", "_plan_validator_action", "_plan_validator_errors",
                "_plan_validator_rounds", "_logical_workflow", "errors",
                "_invocation_budget"),
        produces=("PlanValidatorReport",),
        consumes=("LogicalWorkflow",),
        may_fail=False,
        skip_if="",
        recovery="bounded replan loop → REQUIRE_MORE_INFO → abort",
        output_consumed_by=("CompilerNode", "RequirementCollectorNode", "SemanticPlannerNode"),
    ),
    NodeContract(
        node_id="CompilerNode", phase=NodePhase.COMPILE,
        module="nexus.agent.nodes.compiler_node",
        inputs=("_logical_workflow",),
        reads=("registry", "PlanCache"),
        writes=("_execution_graph", "_graph_version", "errors",
                "_route_to_planner", "_ready_to_plan", "_compile_errors",
                "_compile_retry_count", "_routing_decision",
                "_invocation_budget"),
        produces=("ExecutionGraph",),
        consumes=("LogicalWorkflow",),
        may_fail=True,
        skip_if="",
        recovery=(
            "PlanCache hit / codegen error patch → "
            "bounded replan → response"
        ),
        output_consumed_by=(
            "OptimizerNode", "EstimatorNode", "SemanticPlannerNode", "ResponseNode"
        ),
    ),
    NodeContract(
        node_id="OptimizerNode", phase=NodePhase.COMPILE,
        module="nexus.agent.nodes.optimizer_node",
        inputs=("_execution_graph",),
        reads=("registry",),
        writes=("_execution_graph", "_optimization_snapshots", "_graph_version",
                "iteration_count", "errors"),
        produces=("ExecutionGraph",),
        consumes=("ExecutionGraph",),
        may_fail=False,
        skip_if="graph ≤ optimizer_min_nodes or budget exceeded (routing-level)",
        recovery="bypassed; executor handles defaults/coercion",
        output_consumed_by=("EstimatorNode",),
    ),
    NodeContract(
        node_id="EstimatorNode", phase=NodePhase.COMPILE,
        module="nexus.agent.nodes.estimator_node",
        inputs=("_execution_graph", "_logical_workflow"),
        reads=("settings",),
        writes=("_cost_estimate", "_latency_estimate_ms", "_within_budget", "_estimate_warnings",
                "_execution_strategy", "_execution_strategy_reasons", "_background_execution",
                "_execution_plan"),
        produces=("ExecutionPlan",),
        consumes=("ExecutionGraph",),
        may_fail=False,
        skip_if="",
        recovery="zero-estimate pass-through",
        output_consumed_by=("ValidationNode", "ExecutorNode"),
    ),
    NodeContract(
        node_id="ValidationNode", phase=NodePhase.COMPILE,
        module="nexus.agent.nodes.validation_node",
        inputs=("_execution_graph",),
        reads=(),
        writes=("_validation_result", "_needs_clarification", "_ready_to_plan"),
        produces=("ValidationResult",),
        consumes=("ExecutionGraph",),
        may_fail=False,
        skip_if="",
        recovery="empty/invalid → ResponseNode / RequirementCollector",
        output_consumed_by=("ApprovalGateNode", "ResponseNode", "RequirementCollectorNode"),
    ),
    NodeContract(
        node_id="ApprovalGateNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.nodes.multi_approval_gate_node",
        inputs=("_execution_graph", "_preferred_tools"),
        reads=("registry",),
        writes=("_approval_pending", "_approval_chain_state", "_needs_approval",
                "_pending_approval_tools", "_approval_granted", "_approval_requested_at",
                "_approval_checkpoint_context", "_approval_decision", "_routing_decision",
                "final_response"),
        produces=(),
        consumes=(),
        may_fail=False,
        skip_if="no approval policy matches",
        recovery="rejected → ResponseNode; approved → ExecutorNode",
        output_consumed_by=("ExecutorNode", "ResponseNode"),
    ),
    NodeContract(
        node_id="ApprovalCheckpointResumeNode", phase=NodePhase.ROUTING,
        module="nexus.agent.nodes.approval_checkpoint_resume_node",
        inputs=("_approval_pending", "_approval_checkpoint_context"),
        reads=("LLM",),
        writes=("_approval_decision", "_approval_modification", "_approval_pending",
                "_approval_chain_state",
                "_approval_checkpoint_context", "_needs_approval",
                "_route_to_gate", "_route_to_planner", "_bypass_workflow",
                "_replan_context", "_workflow_dynamic_intent", "_active_workflow_id",
                "_routing_decision", "final_response", "response_type"),
        produces=("approval_decision",),
        consumes=(),
        may_fail=True,
        skip_if="no open approval checkpoint",
        recovery="re-ask / route to gate / modify → planner",
        output_consumed_by=("ApprovalGateNode", "SemanticPlannerNode", "ResponseNode"),
    ),
    NodeContract(
        node_id="ExecutorNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.graph", func_name="executor_node",
        inputs=("_execution_graph", "_graph_patch"),
        reads=("tool registry", "MemoryStore", "artifact graph"),
        writes=("tool_results", "_executor_failed", "_executor_all_success",
                "_tool_executed_in_turn", "_execution_events", "_background_task_id",
                "response_type", "final_response", "errors", "_invocation_budget"),
        produces=("ExecutionEvents", "artifacts"),
        consumes=("ExecutionGraph",),
        may_fail=True,
        skip_if="",
        recovery="typed-status classification → endpoint fallback → reflection retry / replan",
        output_consumed_by=("AggregatorNode", "ResponseNode", "InteractiveWorkflowNode"),
    ),
    NodeContract(
        node_id="AggregatorNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.nodes.aggregator_node",
        inputs=("_execution_graph", "tool_results"),
        reads=("artifact graph",),
        writes=("_aggregated_results",),
        produces=("aggregated_results",),
        consumes=("ReduceNode",),
        may_fail=False,
        skip_if="graph contains no ReduceNodes",
        recovery="silent pass-through",
        output_consumed_by=("ValidatorNode",),
    ),
    NodeContract(
        node_id="ValidatorNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.nodes.validator_node",
        inputs=("tool_results",),
        reads=("registry",),
        writes=("_validation_failed", "_validation_results"),
        produces=("validation_failures",),
        consumes=(),
        may_fail=False,
        skip_if="",
        recovery="typed failures consumed by RecoveryManager",
        output_consumed_by=("RecoveryManagerNode",),
    ),
    NodeContract(
        node_id="RecoveryManagerNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.graph", func_name="recovery_manager_node",
        inputs=("tool_results", "_validation_failed", "_replan_rounds", "_active_workflow_id"),
        reads=(),
        writes=("_recovery_decision", "_recovery_action"),
        produces=("RecoveryDecision",),
        consumes=("typed_failures",),
        may_fail=False,
        skip_if="",
        recovery="RETRY → Reflection / REPLAN → ReplanNode / FAIL → ResponseNode",
        output_consumed_by=("ReflectionNode", "ReplanNode", "ResponseNode"),
    ),
    NodeContract(
        node_id="ReflectionNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.nodes.reflection_node",
        inputs=("_executor_failed", "_execution_graph", "_tool_retry_counts", "_total_retry_count"),
        reads=("settings",),
        writes=("_routing_decision", "_graph_patch", "_tool_retry_counts", "_pending_tasks",
                "_total_retry_count", "_recovery_available", "_recovery_failed_tasks", "errors"),
        produces=("graph_patch",),
        consumes=(),
        may_fail=True,
        skip_if="no failed tasks",
        recovery="quorum → graceful FAIL with compensation; else sub-graph retry",
        output_consumed_by=("ExecutorNode", "ResponseNode"),
    ),
    NodeContract(
        node_id="ReplanNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.nodes.replan_node",
        inputs=("_recovery_decision", "tool_results"),
        reads=(),
        writes=("_replan_context", "_replan_rounds", "_needs_replan",
                "_invocation_budget", "errors"),
        produces=("replan_context",),
        consumes=(),
        may_fail=False,
        skip_if="recovery decision is not replan",
        recovery="planner replans with unavailable ops excluded",
        output_consumed_by=("SemanticPlannerNode",),
    ),
    NodeContract(
        node_id="ResponseNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.nodes.response",
        inputs=("messages", "_structured_payload", "_logical_workflow", "errors",
                "_budget_exceeded", "response_type"),
        reads=("artifact graph", "RendererRegistry", "LLM", "PromptCache"),
        writes=("final_response", "_routing_decision", "response_type", "_synthesis_failed",
                "messages", "working_memory", "errors", "_structured_payload",
                "_invocation_budget", "_response_coverage"),
        produces=("final_response",),
        consumes=("artifacts",),
        may_fail=True,
        skip_if="",
        recovery="degenerate guard → Artifact Renderer fallback → budget renderer",
        output_consumed_by=("MemoryHelperNode",),
    ),
    NodeContract(
        node_id="MemoryHelperNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.nodes.memory_helper_node",
        inputs=("tool_results", "errors", "messages"),
        reads=("artifact graph", "MemoryManager"),
        writes=("_memory_persisted", "_artifact_facts"),
        produces=("memory_entries",),
        consumes=("artifacts",),
        may_fail=True,
        skip_if="no tool work this turn",
        recovery="fire-and-forget (warnings only)",
        output_consumed_by=(),
    ),
    NodeContract(
        node_id="InteractiveWorkflowNode", phase=NodePhase.RUNTIME,
        module="nexus.agent.nodes.interactive_workflow_node",
        inputs=("messages", "_active_workflow_id", "_workflow_definition", "_workflow_collected",
                "_workflow_captured"),
        reads=("artifact graph", "template engine", "LLM"),
        writes=("_active_workflow_id", "_workflow_type", "_workflow_definition",
                "_workflow_steps_total", "_workflow_completed_steps", "_workflow_collected",
                "_workflow_captured", "_workflow_next_action",
                "_workflow_dynamic_pending", "_workflow_dynamic_intent", "_structured_payload",
                "_logical_workflow", "_route_to_compiler", "_route_to_planner",
                "_route_to_router", "_bypass_workflow", "_routing_decision",
                "final_response", "response_type"),
        produces=("workflow_definition", "workflow_artifacts"),
        consumes=(),
        may_fail=True,
        skip_if="no workflow template match",
        recovery="cancel / off-topic escape hatch; same-turn resume finalize",
        output_consumed_by=("CompilerNode", "SemanticPlannerNode", "RouterNode", "ResponseNode"),
    ),
    NodeContract(
        node_id="RequirementCollectorNode", phase=NodePhase.ROUTING,
        module="nexus.agent.nodes.requirement_collector_node",
        inputs=("messages", "intent", "_clarification_slots", "_clarification_rounds"),
        reads=("LLM",),
        writes=("final_response", "_routing_decision", "response_type", "_clarification_asked",
                "_clarification_slots", "_clarification_rounds", "_clarification_consumed_msgs",
                "_clarification_history", "messages", "_ready_to_plan", "_route_to_planner"),
        produces=("clarification_question",),
        consumes=(),
        may_fail=True,
        skip_if="intent confidence ≥ skip threshold",
        recovery="max rounds → force-proceed",
        output_consumed_by=("SemanticPlannerNode",),
    ),
)
