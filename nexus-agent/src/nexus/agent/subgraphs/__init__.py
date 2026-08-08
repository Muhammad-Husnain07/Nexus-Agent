"""Compiler subgraphs — 4-phase pipeline from intent to natural language.

Frontend:  RouterNode → SemanticParserNode → (goal expansion)
Middle-End: Capability resolution → dependency resolution → passes → validation
Backend:   Task graph building → optimization → execution
Codegen:   Reflection → Response (lowering pass)
"""
