"""Frontend — query classification and logical planning.

Nodes: RouterNode, SemanticPlannerNode, RequirementCollectorNode
(KnowledgeAssistantNode merged into ResponseNode's conversational path —
the knowledge goal routes straight to ResponseNode).
"""

from langgraph.graph import StateGraph

from nexus.agent.graph import node, router_node, route_after_requirement_collector
from nexus.agent.nodes.requirement_collector_node import requirement_collector_node as _requirement_collector_node
from nexus.agent.nodes.semantic_parser_node import semantic_parser_node as _semantic_parser_node


def build_frontend(graph: StateGraph, llm: object, model: str) -> None:
    """Register Frontend nodes into the parent graph."""
    graph.add_node("RouterNode", node(router_node, llm, model))
    graph.add_node("SemanticPlannerNode", node(_semantic_parser_node, llm, model))
    graph.add_node("RequirementCollectorNode", node(_requirement_collector_node, llm, model))
