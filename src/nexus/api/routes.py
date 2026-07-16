"""FastAPI router for Nexus Agent API endpoints."""

from fastapi import APIRouter

from nexus.sessions.api import router as sessions_router
from nexus.tools.api import router as tools_router

router = APIRouter()
router.include_router(tools_router)
router.include_router(sessions_router)
