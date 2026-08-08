"""Codegen — response synthesis and memory persistence (Lowering Pass).

Nodes: ResponseNode, MemoryHelperNode
"""

from langgraph.graph import StateGraph

from nexus.agent.graph import node
from nexus.agent.nodes.memory_helper_node import memory_helper_node as _memory_helper_node
from nexus.agent.nodes.response import response_node as _response_node
from nexus.agent.state import AgentState


def build_codegen(graph: StateGraph, llm: object, model: str) -> None:
    """Register Codegen nodes into the parent graph."""
    graph.add_node("ResponseNode", node(_response_node, llm, model))
    graph.add_node("MemoryHelperNode", node(_memory_helper_node, llm, model))
