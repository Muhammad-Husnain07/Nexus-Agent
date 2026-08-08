"""FastAPI router for Nexus Agent API endpoints."""
from fastapi import APIRouter
from nexus.api.chat import router as chat_router
from nexus.api.learning import router as learning_router
from nexus.api.long_running import router as long_running_router
from nexus.api.memory import router as memory_router
from nexus.api.notification import router as notification_router
from nexus.api.projects import router as projects_router
from nexus.api.tasks import router as tasks_router
from nexus.api.websocket import router as ws_router
from nexus.api.workflows import router as workflows_router
from nexus.sessions.api import router as sessions_router
from nexus.tools.api import router as tools_router

router = APIRouter()
router.include_router(tools_router)
router.include_router(sessions_router)
router.include_router(chat_router)
router.include_router(ws_router)
router.include_router(memory_router)
router.include_router(projects_router)
router.include_router(learning_router)
router.include_router(long_running_router)
router.include_router(notification_router)
router.include_router(tasks_router)
router.include_router(workflows_router)
