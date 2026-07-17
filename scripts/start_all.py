import subprocess, sys

# Start Nexus Agent
cmd = [sys.executable, "-m", "uvicorn", "nexus.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
log = open(r"C:\Users\Muhammad Husnain\Desktop\Nexus-Agentic-AI\srv_debug.log", "w", buffering=1)
proc1 = subprocess.Popen(cmd, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)

# Start Content Studio
cmd2 = [sys.executable, "-m", "examples.demo_app.main"]
proc2 = subprocess.Popen(cmd2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

import time
time.sleep(5)

# Seed DB
from nexus.db.base import get_session_factory
from nexus.db.models.tenant import Tenant
from nexus.db.models.user import User
import uuid

async def seed():
    async with get_session_factory()() as s:
        t = Tenant(id=uuid.UUID("11111111-1111-4111-8111-111111111111"), name="Demo", slug="demo")
        await s.merge(t)
        u = User(id=uuid.UUID("00000000-0000-0000-0000-000000000001"), tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"), email="dev@demo.com", role="developer")
        await s.merge(u)
        await s.commit()
    print("DB seeded")

import asyncio
asyncio.run(seed())
print("Servers started")
