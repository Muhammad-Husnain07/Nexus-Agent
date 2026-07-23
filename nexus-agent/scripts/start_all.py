"""Boot all services: proxy + backend + frontend."""

import os, subprocess, sys, time

NEXUS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(os.path.dirname(NEXUS_DIR), "frontend")
VENV = os.path.join(NEXUS_DIR, ".venv", "Scripts", "python.exe")

procs = []

def start(name, cmd, cwd=None):
    p = subprocess.Popen(cmd, cwd=cwd or NEXUS_DIR,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(p)
    print(f"  [{name}] PID={p.pid}")
    return p

print("=" * 50)
print("STARTING ALL SERVICES")
print("=" * 50)

# 1. Web search proxy
print("\n[1/4] Web Search Proxy (port 8081)")
start("Proxy", [VENV, "-m", "uvicorn", "scripts.web_search_server:app",
    "--host", "0.0.0.0", "--port", "8081", "--log-level", "error"])

# 2. Nexus backend
print("\n[2/4] Nexus Backend (port 8000)")
start("Nexus", [VENV, "-m", "uvicorn", "nexus.main:app",
    "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "error"])

# Wait a moment for backend to initialize
time.sleep(3)

# 3. Verify health
import httpx
try:
    r = httpx.get("http://localhost:8000/healthz", timeout=10)
    print(f"\n  Backend health: {r.status_code} {'[OK]' if r.status_code == 200 else '[FAIL]'}")
except Exception as e:
    print(f"\n  Backend health: [FAIL] {e}")

try:
    r = httpx.get("http://localhost:8081/search?q=test", timeout=10)
    print(f"  Proxy health: {r.status_code} {'[OK]' if r.status_code == 200 else '[FAIL]'}")
except Exception as e:
    print(f"  Proxy health: [FAIL] {e}")

# 4. Start frontend
print("\n[3/4] Frontend (port 5173)")
npx = os.path.join(os.environ.get("LOCALAPPDATA", ""), "fnm", "current")
npm_paths = [
    os.path.join(os.environ.get("APPDATA", ""), "npm"),
    r"C:\Program Files\nodejs",
]
npx_cmd = None
for p in npm_paths:
    candidate = os.path.join(p, "npx.cmd")
    if os.path.exists(candidate):
        npx_cmd = candidate
        break

if npx_cmd and os.path.exists(os.path.join(FRONTEND_DIR, "package.json")):
    start("Frontend", [npx_cmd, "vite", "--host"], cwd=FRONTEND_DIR)
    print(f"  Frontend starting from: {FRONTEND_DIR}")
else:
    print(f"  Frontend npx not found. Check Node.js installation.")
    print(f"  To start manually: cd frontend && npx vite --host")

print("\n[4/4] API Documentation")
print(f"  Swagger UI: http://localhost:8000/docs")
print(f"  API Base:   http://localhost:8000/api/v1")

print("\n" + "=" * 50)
print("SERVICES RUNNING")
print("  Backend:  http://localhost:8000")
print("  Proxy:    http://localhost:8081")
print("  Frontend: http://localhost:5173")
print("=" * 50)
print("\nPress Ctrl+C to stop all services.")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nShutting down...")
    for p in procs:
        p.terminate()
    for p in procs:
        try: p.wait(timeout=5)
        except: p.kill()
    print("Done.")
