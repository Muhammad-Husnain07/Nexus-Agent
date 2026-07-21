import subprocess
import sys
cmd = [sys.executable, "-m", "uvicorn", "nexus.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--log-level", "debug"]
log = open(r"C:\Users\Muhammad Husnain\Desktop\Nexus-Agentic-AI\srv_debug.log", "w", buffering=1)
proc = subprocess.Popen(cmd, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
open(r"C:\Users\Muhammad Husnain\Desktop\Nexus-Agentic-AI\srv_pid.txt", "w").write(str(proc.pid))
print(f"PID: {proc.pid}")
