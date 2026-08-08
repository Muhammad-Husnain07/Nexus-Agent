"""Identity → ResolverContext bridging.

Builds a ``ResolverContext`` from a verified identity (permissions, tier,
preferred version/environment) so capability resolution and permission
scoring reflect the caller. Falls back to defaults when no identity is
present (anonymous).
"""

from __future__ import annotations

from typing import Any

from nexus.capabilities.resolver import ResolverContext


def resolver_context_from_state(
    state: dict[str, Any],
    environment: str | None = None,
) -> ResolverContext:
    """Build a ResolverContext from agent state + optional environment.

    Args:
        state: The AgentState dict (may carry user identity under
            ``user_context``).
        environment: Active deployment environment name (overrides).

    Returns:
        A ResolverContext carrying permissions/tier/version/environment.
    """
    user_context = state.get("user_context") or {}
    permissions = list(user_context.get("permissions") or [])
    tier = user_context.get("tier")
    preferred_version = user_context.get("preferred_version")

    return ResolverContext(
        user_permissions=permissions,
        user_tier=tier,
        preferred_version=preferred_version,
        environment=environment,
    )
