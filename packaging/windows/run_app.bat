@echo off
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI\"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%check_launch_ports.ps1" -BackendPort %BACKEND_PORT% -FrontendPort %FRONTEND_PORT%
if errorlevel 1 exit /b 1

start "Backend" /D "%ROOT%backend" cmd /k "set COPYLOT_AI_MODE=0 && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --workers 1 --host 127.0.0.1 --port %BACKEND_PORT%"

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
  echo Warning: backend on port %BACKEND_PORT% is not ready yet.
)

start "Frontend" /D "%ROOT%frontend" cmd /k "set VITE_AI_ENABLED=0 && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
timeout /t 2 /nobreak >nul
start "" "http://localhost:%FRONTEND_PORT%"
