"""Three-tier context architecture for the Agent OS.

- GlobalContext: Immutable per-deployment (compiled graph, ontology, schemas).
- SessionContext: Slow-changing per-session (user, policies, memory refs).
- ExecutionContext: Fast-changing per-node (version, IR stack, artifact/execution IDs).
"""
