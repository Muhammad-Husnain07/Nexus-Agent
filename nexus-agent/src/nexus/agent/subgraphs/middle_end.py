"""Middle-End — capability resolution, optimization, validation.

Nodes: CompilerNode, OptimizerNode, EstimatorNode, ValidationNode
(DecompositionNode and PlanCriticNode removed — dead/unreachable branches;
see docs/adrs/cleanup).
"""

from langgraph.graph import StateGraph

from nexus.agent.graph import node
from nexus.agent.nodes.compiler_node import compiler_node as _compiler_node
from nexus.agent.nodes.estimator_node import estimator_node as _estimator_node
from nexus.agent.nodes.optimizer_node import optimizer_node as _optimizer_node
from nexus.agent.nodes.validation_node import validation_node as _validation_node
from nexus.agent.state import AgentState


def build_middle_end(graph: StateGraph, llm: object, model: str) -> None:
    """Register Middle-End nodes into the parent graph."""
    graph.add_node("CompilerNode", node(_compiler_node))
    graph.add_node("OptimizerNode", node(_optimizer_node))
    graph.add_node("EstimatorNode", node(_estimator_node))
    graph.add_node("ValidationNode", node(_validation_node))
