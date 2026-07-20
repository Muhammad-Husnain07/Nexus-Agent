"""Minimal FastAPI dependencies — hardcoded tenant/user IDs."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request

from nexus.utils.constants import DEFAULT_TENANT_ID_STR, DEFAULT_USER_ID_STR


async def _current_tenant(request: Request) -> uuid.UUID:
    tid = getattr(request.state, "tenant_id", None)
    if tid is not None:
        return uuid.UUID(str(tid)) if isinstance(tid, str) else tid
    return uuid.UUID(DEFAULT_TENANT_ID_STR)


async def _current_user(request: Request) -> uuid.UUID:
    uid = getattr(request.state, "user_id", None)
    if uid is not None:
        return uuid.UUID(str(uid)) if isinstance(uid, str) else uid
    return uuid.UUID(DEFAULT_USER_ID_STR)


TenantDep = Annotated[uuid.UUID, Depends(_current_tenant)]
UserDep = Annotated[uuid.UUID, Depends(_current_user)]
