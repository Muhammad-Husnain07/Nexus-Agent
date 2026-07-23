"""Start the Vite dev server as a background process."""
import subprocess, sys, time
cmd = [r"C:\nvm4w\nodejs\npx.cmd", "vite", "--host", "0.0.0.0", "--port", "5173"]
log = open(r"C:\Users\Muhammad Husnain\Desktop\Nexus-Agentic-AI\vite_debug.log", "w", buffering=1)
proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=r"C:\Users\Muhammad Husnain\Desktop\Nexus-Agentic-AI\frontend")
print(f"Vite PID: {proc.pid}")
