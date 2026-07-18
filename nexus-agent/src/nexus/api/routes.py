"""FastAPI router for Nexus Agent API endpoints."""

from fastapi import APIRouter

from nexus.api.admin import router as admin_router
from nexus.api.approvals import router as approvals_router
from nexus.api.chat import router as chat_router
from nexus.api.memory import router as memory_router
from nexus.api.websocket import router as ws_router
from nexus.observability.cost import router as cost_router
from nexus.security.auth import router as auth_router
from nexus.sessions.api import router as sessions_router
from nexus.tools.api import router as tools_router

router = APIRouter()
router.include_router(tools_router)
router.include_router(sessions_router)
router.include_router(approvals_router)
router.include_router(chat_router)
router.include_router(ws_router)
router.include_router(admin_router)
router.include_router(auth_router)
router.include_router(cost_router)
router.include_router(memory_router)
