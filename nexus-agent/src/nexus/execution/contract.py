"""ExecutionContract — the universal boundary model (Phase 9).

Every executable — capability, workflow, macro, composite, background job —
normalizes to one contract: inputs, outputs, permissions, policies,
guarantees, rollback, timeout, checkpoint, expected artifacts. No special
cases: consumers read ONE shape.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nexus.execution.policy import ExecutionPolicy, policy_from_contract


class ExecutionContract(BaseModel):
    """The shared contract implemented by every executable."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Executable name (display)")
    executable_type: str = Field(
        description="capability | workflow | macro | composite | background_job"
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict, description="Declared input schema (properties)"
    )
    outputs: dict[str, Any] = Field(
        default_factory=dict, description="Declared output schema (properties)"
    )
    permissions: tuple[str, ...] = Field(
        default_factory=tuple, description="Required permission scopes"
    )
    policies: ExecutionPolicy = Field(
        default_factory=ExecutionPolicy, description="Execution behavior (timeout/retry/approval/…)"
    )
    guarantees: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Reliability guarantees (at_least_once, idempotent, …)",
    )
    rollback: str | None = Field(default=None, description="Undo executable (saga compensation)")
    timeout_s: float = Field(default=20.0, description="Per-invocation timeout")
    checkpoint: bool = Field(default=False, description="Execution may pause/resume (approvals)")
    expected_artifacts: tuple[str, ...] = Field(
        default_factory=tuple, description="Artifact names this executable produces"
    )


def contract_from_metadata(
    name: str,
    executable_type: str,
    contract_block: dict[str, Any] | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    produces: list[str] | None = None,
    rollback: str | None = None,
) -> ExecutionContract:
    """Normalize any metadata-shaped executable to an ExecutionContract.

    Metadata-driven: missing fields degrade to safe defaults — never guesses.
    """
    policy = policy_from_contract(contract_block) if contract_block else ExecutionPolicy()

    def _props(schema: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {}
        props = schema.get("properties")
        return props if isinstance(props, dict) else {}

    return ExecutionContract(
        name=name,
        executable_type=executable_type,
        inputs=_props(input_schema),
        outputs=_props(output_schema),
        permissions=tuple(policy.permissions),
        policies=policy,
        guarantees=("idempotent",) if policy.idempotent else (),
        rollback=policy.rollback or rollback,
        timeout_s=policy.timeout_s,
        checkpoint=policy.requires_approval,
        expected_artifacts=tuple(str(p) for p in (produces or [])),
    )


def contract_from_tool(tool: Any) -> ExecutionContract:
    """Normalize a Tool (ORM or ToolRead-like) to an ExecutionContract."""
    try:
        contract_block = getattr(tool, "contract", None)
    except Exception:
        contract_block = None
    if not isinstance(contract_block, dict):
        try:
            from nexus.execution.policy import policy_from_contract

            contract_block = {
                "idempotent": bool(getattr(tool, "idempotent", False)),
                "risk_level": str(getattr(tool, "risk_level", None) or "low"),
                "requires_approval": bool(getattr(tool, "requires_approval", False)),
                "cacheable": bool(getattr(tool, "cacheable", True)),
            }
        except Exception:
            contract_block = None
    return contract_from_metadata(
        name=str(getattr(tool, "name", "")),
        executable_type="capability",
        contract_block=contract_block,
        input_schema=getattr(tool, "input_schema", None),
        output_schema=getattr(tool, "output_schema", None),
        produces=getattr(tool, "produces", None),
        rollback=getattr(tool, "compensating_operation", None),
    )


def contract_from_workflow(workflow: dict[str, Any]) -> ExecutionContract:
    """Normalize a workflow definition dict to an ExecutionContract."""
    steps = workflow.get("steps") or []
    step_names = [str(s.get("id") or s.get("intent") or s.get("capability") or "") for s in steps]
    return contract_from_metadata(
        name=str(workflow.get("name") or ""),
        executable_type="workflow",
        contract_block={
            "timeout_s": float(workflow.get("timeout_s") or 30.0),
            "retries": 0,
            "parallel": True,
            "risk_level": "low",
            "requires_approval": False,
            "idempotent": False,
            "cacheable": False,
        },
        produces=[f"workflow:{name}" for name in step_names if name],
    )


def contract_from_plan_node(node: dict[str, Any]) -> ExecutionContract:
    """Normalize a logical plan node to an ExecutionContract."""
    return contract_from_metadata(
        name=str(node.get("op") or node.get("ref") or ""),
        executable_type=str(node.get("kind") or "capability"),
        input_schema={"properties": node.get("inputs") or {}},
        produces=node.get("produces"),
        rollback=node.get("rollback"),
    )
