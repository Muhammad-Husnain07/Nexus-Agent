"""Start proxy server + Nexus server, then run comprehensive tests."""

import asyncio
import logging
import os
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def wait_for_url(url: str, timeout: int = 60, interval: float = 2.0) -> bool:
    """Wait until a URL returns 200."""
    import httpx
    start = time.time()
    async with httpx.AsyncClient(timeout=5) as c:
        while time.time() - start < timeout:
            try:
                r = await c.get(url)
                if r.status_code < 500:
                    return True
            except Exception:
                pass
            await asyncio.sleep(interval)
    return False


async def main():
    nexus_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_python = os.path.join(nexus_dir, ".venv", "Scripts", "python.exe")
    
    # Start web search proxy
    log.info("Starting web search proxy on port 8081...")
    proxy_proc = subprocess.Popen(
        [venv_python, "-m", "uvicorn", "scripts.web_search_server:app",
         "--host", "0.0.0.0", "--port", "8081"],
        cwd=nexus_dir,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    
    # Start Nexus server
    log.info("Starting Nexus Agent on port 8000...")
    nexus_proc = subprocess.Popen(
        [venv_python, "-m", "uvicorn", "nexus.main:app",
         "--host", "0.0.0.0", "--port", "8000", "--workers", "1"],
        cwd=nexus_dir,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    
    try:
        # Wait for servers
        log.info("Waiting for Nexus server...")
        nexus_ready = await wait_for_url("http://localhost:8000/healthz", timeout=120)
        if not nexus_ready:
            log.error("Nexus server failed to start")
            return
        
        log.info("Waiting for proxy...")
        proxy_ready = await wait_for_url("http://localhost:8081/search?q=test", timeout=30)
        if not proxy_ready:
            log.warning("Proxy may not be ready, continuing anyway")
        
        log.info("Both servers ready!\n")
        
        # Run tests
        from scripts.run_all import main as run_tests
        await run_tests()
        
    finally:
        log.info("\nShutting down servers...")
        nexus_proc.terminate()
        proxy_proc.terminate()
        nexus_proc.wait()
        proxy_proc.wait()
        log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
