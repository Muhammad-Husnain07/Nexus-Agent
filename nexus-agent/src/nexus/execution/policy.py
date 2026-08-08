"""ExecutionPolicy — declarative execution behavior for a capability.

One metadata block answers: timeout, retries, parallelism, risk, approval,
idempotency, cacheability, budget, permissions, rollback. The executor,
approval gate, estimator, and validator read THIS block (legacy contract keys
remain readable for backward compatibility — readers never break).

Frozen, typed, metadata-driven. No tool-name logic anywhere.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionPolicy(BaseModel):
    """Declarative execution behavior (built from capability metadata)."""

    model_config = ConfigDict(frozen=True)

    timeout_s: float = Field(default=20.0, description="Per-call timeout in seconds")
    retries: int = Field(default=0, description="Max auto-retries (idempotent tools only)")
    parallel: bool = Field(default=True, description="May execute in parallel with siblings")
    risk_level: str = Field(default="low", description="low | medium | high")
    requires_approval: bool = Field(default=False, description="Pause for conversational approval")
    idempotent: bool = Field(default=False, description="Safe to auto-retry (single side effect)")
    cacheable: bool = Field(default=True, description="Result may be reused (freshness hint)")
    budget_usd: float | None = Field(default=None, description="Per-invocation cost cap (None = unlimited)")
    permissions: tuple[str, ...] = Field(default_factory=tuple, description="Required permission scopes")
    rollback: str | None = Field(
        default=None, description="Tool name that UNDOES this capability's side effects"
    )
    maintenance_windows: tuple[str, ...] = Field(
        default_factory=tuple, description="ISO-8601 maintenance windows (unavailable during)"
    )


def policy_from_contract(contract: Any) -> ExecutionPolicy:
    """Build the policy from a capability contract, with legacy-key fallback.

    Prefers the unified ``execution_policy`` block; falls back to the legacy
    top-level contract keys (idempotent/risk_level/requires_approval/cacheable)
    so old registry rows stay readable. Defaults are never guessed — missing
    metadata yields safe defaults.
    """
    if not isinstance(contract, dict):
        contract = {}
    block = contract.get("execution_policy")
    if isinstance(block, dict) and block:
        base = {
            "timeout_s": block.get("timeout_s", 20.0),
            "retries": block.get("retries", 0),
            "parallel": block.get("parallel", True),
            "risk_level": block.get("risk_level", "low"),
            "requires_approval": block.get("requires_approval", False),
            "idempotent": block.get("idempotent", False),
            "cacheable": block.get("cacheable", True),
            "budget_usd": block.get("budget_usd"),
            "permissions": tuple(block.get("permissions") or ()),
            "rollback": block.get("rollback"),
            "maintenance_windows": tuple(block.get("maintenance_windows") or ()),
        }
        return ExecutionPolicy(**base)

    return ExecutionPolicy(
        timeout_s=float(contract.get("timeout_s") or 20.0),
        retries=int(contract.get("retries") or 0),
        parallel=bool(contract.get("parallel", True)),
        risk_level=str(contract.get("risk_level") or "low"),
        requires_approval=bool(contract.get("requires_approval", False)),
        idempotent=bool(contract.get("idempotent", False)),
        cacheable=bool(contract.get("cacheable", True)),
        budget_usd=contract.get("budget_usd"),
        permissions=tuple(contract.get("permissions") or ()),
        rollback=contract.get("rollback") or contract.get("compensating_operation"),
        maintenance_windows=tuple(contract.get("maintenance_windows") or ()),
    )


def policy_for_capability(name: str) -> ExecutionPolicy:
    """Policy for a capability from GlobalContext metadata (lazy, safe)."""
    try:
        from nexus.context import global_context as _gc_mod

        meta = (getattr(_gc_mod.get_global_context(), "capability_index", {}) or {}).get(name, {})
        contract = meta.get("contract")
        if isinstance(contract, dict):
            return policy_from_contract(contract)
        return policy_from_contract(meta)
    except Exception:
        return ExecutionPolicy()
