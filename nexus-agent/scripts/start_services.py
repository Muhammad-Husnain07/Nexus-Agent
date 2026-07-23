"""Start all services and save status to a log file."""
import os, subprocess, sys, time, httpx

log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'startup.log')
log_file = open(log_path, 'w', encoding='utf-8')

def log(msg):
    print(msg, flush=True)
    log_file.write(msg + '\n')
    log_file.flush()

nexus_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_dir = os.path.join(os.path.dirname(nexus_dir), 'frontend')
venv = os.path.join(nexus_dir, '.venv', 'Scripts', 'python.exe')
procs = []

# Kill old processes first
subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], capture_output=True)
subprocess.run(['taskkill', '/F', '/IM', 'uvicorn.exe'], capture_output=True)
time.sleep(1)

log("=== Starting Services ===")

# 1. Proxy
p = subprocess.Popen([venv, '-m', 'uvicorn', 'scripts.web_search_server:app',
    '--host', '0.0.0.0', '--port', '8081', '--log-level', 'error'],
    cwd=nexus_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
procs.append(('Proxy', p))
log(f"[Proxy] PID={p.pid}")

# 2. Nexus
p = subprocess.Popen([venv, '-m', 'uvicorn', 'nexus.main:app',
    '--host', '0.0.0.0', '--port', '8000', '--workers', '1', '--log-level', 'error'],
    cwd=nexus_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
procs.append(('Nexus', p))
log(f"[Nexus] PID={p.pid}")

# Wait
for i in range(30):
    nx = False
    try: nx = httpx.get('http://localhost:8000/healthz', timeout=2).status_code == 200
    except: pass
    px = False
    try: px = httpx.get('http://localhost:8081/search?q=test', timeout=2).status_code == 200
    except: pass
    if nx and px: break
    time.sleep(2)

log(f"[Nexus] {'OK' if nx else 'FAIL'}")
log(f"[Proxy] {'OK' if px else 'FAIL'}")

# 3. Frontend
npx = None
for p in [r'C:\Program Files\nodejs\npx.cmd',
          os.path.join(os.environ.get('APPDATA',''),'npm','npx.cmd')]:
    if os.path.exists(p): npx = p; break

if npx and os.path.exists(os.path.join(frontend_dir, 'package.json')):
    p = subprocess.Popen([npx, 'vite', '--host'], cwd=frontend_dir,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(('Frontend', p))
    log(f"[Frontend] PID={p.pid}")
else:
    log(f"[Frontend] npx not found. Run: cd frontend && npx vite --host")

# 4. Save PIDs
with open(os.path.join(nexus_dir, 'running_pids.txt'), 'w') as f:
    for name, p in procs: f.write(f'{name}:{p.pid}\n')

log("")
log("=" * 50)
log("ALL SERVICES RUNNING")
log(f"  Backend:  http://localhost:8000  (API docs: /docs)")
log(f"  Proxy:    http://localhost:8081")
log(f"  Frontend: http://localhost:5173")
log("=" * 50)
log_file.close()
