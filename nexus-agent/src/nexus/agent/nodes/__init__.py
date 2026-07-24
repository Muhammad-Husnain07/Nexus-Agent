"""Graph node implementations — one module per node.

Only ``finalize`` is used by the current 5-node production graph.
Legacy node modules have been removed.  Add new node modules here.
"""

from nexus.agent.nodes.finalize import finalize

__all__ = ["finalize"]
