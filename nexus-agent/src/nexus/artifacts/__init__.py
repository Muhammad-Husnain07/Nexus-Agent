"""Artifact ABI — typed, traceable tool output models.

Every tool execution produces an ``ArtifactBase`` registered in the
``ArtifactGraph``.  Downstream nodes (ResponseNode, AggregatorNode)
read artifacts by type/ID instead of raw JSON blobs.
"""
