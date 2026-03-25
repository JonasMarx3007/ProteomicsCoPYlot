@echo off
set "ROOT=%~dp0"
start "Backend (Viewer)" /D "%ROOT%backend" cmd /k "set COPYLOT_VIEWER_MODE=1 && set COPYLOT_VIEWER_CONFIG=%ROOT%viewer_config.json && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port 8001"
start "Frontend (Viewer)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_PROXY_TARGET=http://127.0.0.1:8001 && npm run dev -- --port 5174"
timeout /t 3 /nobreak >nul
start "" "http://localhost:5174"
