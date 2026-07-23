@echo off
cd /d "%~dp0.."
echo Starting Web Search Proxy on port 8081...
start "WebProxy" /b .venv\Scripts\python.exe -m uvicorn scripts.web_search_server:app --host 0.0.0.0 --port 8081
timeout /t 3 /nobreak >nul

echo Starting Nexus Agent on port 8000...
start "NexusServer" /b .venv\Scripts\python.exe -m uvicorn nexus.main:app --host 0.0.0.0 --port 8000 --workers 1
timeout /t 8 /nobreak >nul

echo Running comprehensive tests...
.venv\Scripts\python.exe scripts\run_all.py
pause
