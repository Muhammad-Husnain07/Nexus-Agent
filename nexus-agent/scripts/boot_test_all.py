"""Boot servers and run comprehensive real-time tests in a single process."""

import asyncio
import logging
import os
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger(__name__)

NEXUS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(NEXUS_DIR, ".venv", "Scripts", "python.exe")


def start_server(name: str, module: str, port: int):
    """Start a uvicorn server as a subprocess."""
    proc = subprocess.Popen(
        [VENV, "-m", "uvicorn", module, "--host", "0.0.0.0", "--port", str(port), "--log-level", "error"],
        cwd=NEXUS_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.info(f"  {name} starting (PID={proc.pid})...")
    return proc


async def main():
    log.info("=" * 60)
    log.info("BOOTING SERVERS")
    log.info("=" * 60)
    
    # Start proxy server
    proxy = start_server("Proxy", "scripts.web_search_server:app", 8081)
    
    # Start nexus server
    nexus = start_server("Nexus", "nexus.main:app", 8000)
    
    # Wait for both
    import httpx
    for attempt in range(60):
        nexus_ok = False
        proxy_ok = False
        try:
            r = await httpx.AsyncClient(timeout=5).get("http://localhost:8000/healthz")
            nexus_ok = r.status_code == 200
        except Exception:
            pass
        try:
            r = await httpx.AsyncClient(timeout=5).get("http://localhost:8081/search?q=test")
            proxy_ok = r.status_code == 200
        except Exception:
            pass
        if nexus_ok and proxy_ok:
            break
        await asyncio.sleep(2)
    
    log.info(f"  Nexus: {'[OK]' if nexus_ok else '[FAIL]'}")
    log.info(f"  Proxy: {'[OK]' if proxy_ok else '[FAIL]'}")
    
    if not nexus_ok:
        log.error("Nexus server failed to start")
        nexus.kill()
        proxy.kill()
        return
    
    # Run tests
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import start_servers  # noqa: PLC0415
    await start_servers.main()
    
    # Cleanup
    log.info("\nShutting down servers...")
    nexus.terminate()
    proxy.terminate()
    nexus.wait(timeout=10)
    proxy.wait(timeout=10)
    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
