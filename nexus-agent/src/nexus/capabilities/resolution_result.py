"""ResolutionResult — typed contract for capability/workflow resolution.

One frozen object consumed by every subsystem that needs to know "what is
relevant": the router (binary facts only), the planner (ranked candidates with
scores/confidence/reasons), and telemetry (explanation). Immutable end-to-end;
consumers copy when they need to derive.

The ``CandidateBase`` shape is the seed of the future unified executable
candidate space (roadmap Phase 9) — capability and workflow candidates share
it, so merging the two streams later requires no model surgery.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Confidence = Literal["high", "medium", "low"]
Availability = Literal[
    "available",
    "unavailable",
    "disabled",
    "rate_limited",
    "maintenance",
    "permission_denied",
]


class CandidateBase(BaseModel):
    """Shared candidate shape (capability / workflow / future executables)."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Stable ID (tool.id / workflow row id) — names change, IDs don't")
    name: str = Field(description="Display name (capability logical op / workflow name)")
    executable_type: str = Field(
        default="capability",
        description="capability | workflow | macro | composite | background_job (Phase 9)",
    )
    score: float = Field(description="Match score (retriever / matcher specific scale)")
    confidence: Confidence = Field(description="Confidence band (see ConfidenceClassifier)")
    match_sources: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Layers that matched: alias | example | keyword | domain | bm25 | fuzzy | metadata",
    )
    reasons: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Human-readable match explanations (debug/telemetry only — never parsed)",
    )


class CapabilityCandidate(CandidateBase):
    """A ranked capability candidate with its availability facts."""

    domain: str = Field(default="", description="Capability domain/category")
    availability: Availability = Field(
        default="available",
        description=(
            "Availability fact resolved BEFORE planning (enabled, circuit "
            "state, rate-limit headroom). Unavailable candidates are excluded "
            "from the planner stream."
        ),
    )
    availability_reason: str | None = Field(
        default=None, description="Why the availability state holds (debug only)"
    )


class WorkflowCandidate(CandidateBase):
    """A ranked workflow-template candidate."""

    tags: tuple[str, ...] = Field(default_factory=tuple, description="Template tags (metadata boost)")


class ResolutionMetadata(BaseModel):
    """Typed metadata about a resolution run — never a generic dict."""

    model_config = ConfigDict(frozen=True)

    elapsed_ms: float = Field(description="Resolution wall time")
    catalog_size: int = Field(description="Capabilities considered (post-prefilters)")
    fingerprint: str = Field(
        default="", description="Content hash of registry state (registry_checksum + tool marker)"
    )
    registry_version: int = Field(
        default=0, description="Incrementing registry version — distinct from the content hash"
    )
    layers_run: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Pipeline layers executed in order (alias, boost, domain, bm25, workflow)",
    )
    resolver_version: int = Field(default=1, description="ResolutionEngine semantic version")


class ResolutionResult(BaseModel):
    """The immutable output of the ResolutionEngine."""

    model_config = ConfigDict(frozen=True)

    query: str = Field(description="The query that was resolved")
    domain_hint: str | None = Field(default=None, description="Deterministic domain hint applied")
    workflow_candidates: tuple[WorkflowCandidate, ...] = Field(
        default_factory=tuple, description="Ranked workflow-template candidates"
    )
    capability_candidates: tuple[CapabilityCandidate, ...] = Field(
        default_factory=tuple, description="Ranked, available capability candidates (top-K)"
    )
    has_capability_candidates: bool = Field(
        default=False, description="Fact: any available capability candidates"
    )
    has_workflow_candidates: bool = Field(
        default=False, description="Fact: any workflow-template candidates"
    )
    metadata: ResolutionMetadata = Field(description="Typed resolution metadata")
    explanation: str = Field(
        default="",
        description=(
            "Human-readable 'why did this match' narrative — for /debug, "
            "LangSmith, and telemetry. Never consumed by routing or planning."
        ),
    )

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        """All candidate IDs across both streams (ordered)."""
        return tuple(
            c.id
            for c in (*self.capability_candidates, *self.workflow_candidates)
        )

    @property
    def executable_candidates(self) -> tuple[CandidateBase, ...]:
        """Unified executable candidate space (Phase 9): one ranked list,
        each candidate tagged with its ``executable_type``. Capabilities rank
        above workflows (capability stream is the primary planner input);
        the planner may reason over this merged space directly."""
        return (*self.capability_candidates, *self.workflow_candidates)


class _ResolutionResultPublic(BaseModel):
    """Alias for API surface naming (no-op)."""

    model_config = ConfigDict(frozen=True)

    resolution_result: ResolutionResult = Field(description="The resolution result")

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - trivial passthrough
        return getattr(self.resolution_result, item)
