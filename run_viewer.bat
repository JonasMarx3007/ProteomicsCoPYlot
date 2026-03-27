@echo off
set "ROOT=%~dp0"

set "BACKEND_PORT=8001"

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %BACKEND_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
  start "Backend (Viewer)" /D "%ROOT%backend" cmd /k "set COPYLOT_VIEWER_MODE=1 && set COPYLOT_VIEWER_CONFIG=%ROOT%viewer_config.json && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
)

set "BACKEND_READY=0"
for /l %%i in (1,1,20) do (
  powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %BACKEND_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
  if not errorlevel 1 (
    set "BACKEND_READY=1"
    goto :backend_ready
  )
  timeout /t 1 /nobreak >nul
)

:backend_ready
if "%BACKEND_READY%"=="0" (
  echo Warning: viewer backend on port %BACKEND_PORT% is not ready yet.
)

start "Frontend (Viewer)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port 5174"
timeout /t 2 /nobreak >nul
start "" "http://localhost:5174"
