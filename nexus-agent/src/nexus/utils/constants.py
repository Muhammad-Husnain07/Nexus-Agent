"""Shared constants used across the Nexus Agent codebase."""

from __future__ import annotations

import uuid

DEFAULT_TENANT_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_USER_ID: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

DEFAULT_TENANT_ID_STR: str = str(DEFAULT_TENANT_ID)
DEFAULT_USER_ID_STR: str = str(DEFAULT_USER_ID)
