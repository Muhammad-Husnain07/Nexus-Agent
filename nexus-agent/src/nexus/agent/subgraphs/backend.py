"""Backend — approval, execution, aggregation, validation, reflection.

Nodes: ApprovalGateNode, ExecutorNode, AggregatorNode, ValidatorNode,
       ReflectionNode
(SelfHealingNode removed — its patch had no consumers; endpoint fallback
lives inside the ConcurrentExecutor).
"""

from langgraph.graph import StateGraph

from nexus.agent.graph import executor_node, node
from nexus.agent.nodes.aggregator_node import aggregator_node as _aggregator_node
from nexus.agent.nodes.multi_approval_gate_node import multi_approval_gate_node as _multi_approval_gate_node
from nexus.agent.nodes.reflection_node import reflection_node as _reflection_node
from nexus.agent.nodes.validator_node import validator_node as _validator_node
from nexus.agent.state import AgentState


def build_backend(graph: StateGraph, tool_executor: object) -> None:
    """Register Backend nodes into the parent graph."""
    graph.add_node("ApprovalGateNode", node(_multi_approval_gate_node))
    graph.add_node("ExecutorNode", node(executor_node, tool_executor))
    graph.add_node("AggregatorNode", node(_aggregator_node))
    graph.add_node("ValidatorNode", node(_validator_node))
    graph.add_node("ReflectionNode", node(_reflection_node))
