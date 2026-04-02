@echo off
setlocal EnableDelayedExpansion
set "ROOT=%~dp0"

set "BACKEND_PORT=8001"
set "FRONTEND_PORT=5174"
set "CHAT_MODEL=%~1"

if defined CHAT_MODEL (
  if "!CHAT_MODEL:~0,2!"=="--" set "CHAT_MODEL=!CHAT_MODEL:~2!"
)

if defined CHAT_MODEL (
  where ollama >nul 2>&1
  if errorlevel 1 (
    echo Warning: ollama executable not found in PATH. Skipping model pull for "!CHAT_MODEL!".
  ) else (
    echo Pulling Ollama model "!CHAT_MODEL!"...
    ollama pull "!CHAT_MODEL!"
    if errorlevel 1 (
      echo Warning: failed to pull model "!CHAT_MODEL!". Continuing startup.
    )
  )
)

for /f %%P in ('powershell -NoProfile -Command "$conn = Get-NetTCPConnection -LocalPort %BACKEND_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { $conn.OwningProcess }"') do set "BACKEND_PID=%%P"
if defined BACKEND_PID (
  powershell -NoProfile -Command "Stop-Process -Id %BACKEND_PID% -Force -ErrorAction SilentlyContinue" >nul 2>&1
  timeout /t 1 /nobreak >nul
)

for /f %%P in ('powershell -NoProfile -Command "$conn = Get-NetTCPConnection -LocalPort %FRONTEND_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { $conn.OwningProcess }"') do set "FRONTEND_PID=%%P"
if defined FRONTEND_PID (
  powershell -NoProfile -Command "Stop-Process -Id %FRONTEND_PID% -Force -ErrorAction SilentlyContinue" >nul 2>&1
  timeout /t 1 /nobreak >nul
)

if defined CHAT_MODEL (
  start "Backend (Viewer AI)" /D "%ROOT%backend" cmd /k "set COPYLOT_VIEWER_MODE=1 && set COPYLOT_VIEWER_CONFIG=%ROOT%viewer_config.json && set COPYLOT_AI_MODE=1 && set COPYLOT_OLLAMA_MODEL=!CHAT_MODEL! && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
) else (
  start "Backend (Viewer AI)" /D "%ROOT%backend" cmd /k "set COPYLOT_VIEWER_MODE=1 && set COPYLOT_VIEWER_CONFIG=%ROOT%viewer_config.json && set COPYLOT_AI_MODE=1 && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
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

start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
timeout /t 2 /nobreak >nul
start "" "http://localhost:%FRONTEND_PORT%"
