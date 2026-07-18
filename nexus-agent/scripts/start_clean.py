"""Start Nexus API and Content Studio servers cleanly."""
import subprocess, sys, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)

# Seed DB first
sys.path.insert(0, ROOT)
from nexus.db.base import get_session_factory
from nexus.db.models.tenant import Tenant
from nexus.db.models.user import User
import uuid, asyncio

async def seed():
    async with get_session_factory()() as s:
        t = Tenant(id=uuid.UUID("11111111-1111-4111-8111-111111111111"), name="Demo", slug="demo")
        await s.merge(t)
        u = User(id=uuid.UUID("00000000-0000-0000-0000-000000000001"), tenant_id=uuid.UUID("11111111-1111-4111-8111-111111111111"), email="dev@demo.com", role="developer")
        await s.merge(u)
        await s.commit()

asyncio.run(seed())
print("DB seeded")

log = open(os.path.join(ROOT, "srv_debug.log"), "w", buffering=1)

# Start Nexus Agent
cmd1 = [sys.executable, "-m", "uvicorn", "nexus.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
proc1 = subprocess.Popen(cmd1, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
print(f"Nexus started (PID {proc1.pid})")

# Start Content Studio
cmd2 = [sys.executable, "-m", "examples.demo_app.main"]
proc2 = subprocess.Popen(cmd2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
print(f"Studio started (PID {proc2.pid})")

time.sleep(5)
print("Servers ready")
