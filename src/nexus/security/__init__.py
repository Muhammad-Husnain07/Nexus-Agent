"""Authentication, authorization, RBAC, scopes, quotas, audits, and guards."""

from nexus.security.audit import AuditLogger
from nexus.security.auth import (
    create_access_token,
    create_refresh_token,
    generate_api_key,
    hash_api_key,
    verify_api_key,
    verify_jwt,
)
from nexus.security.input_guard import OutputGuard, PromptInjectionGuard
from nexus.security.quota import QuotaEnforcer
from nexus.security.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    Role,
    get_current_user,
    require_permission,
    require_user,
)
from nexus.security.scopes import can_delete_tools, can_register_tools, filter_tools_by_role

__all__ = [
    "Role",
    "Permission",
    "ROLE_PERMISSIONS",
    "get_current_user",
    "require_permission",
    "require_user",
    "can_register_tools",
    "can_delete_tools",
    "filter_tools_by_role",
    "QuotaEnforcer",
    "AuditLogger",
    "create_access_token",
    "create_refresh_token",
    "generate_api_key",
    "hash_api_key",
    "verify_api_key",
    "verify_jwt",
    "PromptInjectionGuard",
    "OutputGuard",
]
