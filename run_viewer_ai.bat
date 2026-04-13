@echo off
setlocal EnableDelayedExpansion
set "ROOT=%~dp0"

set "BACKEND_PORT=8001"
set "FRONTEND_PORT=5174"
set "CHAT_MODEL="
set "DEV_MODE=0"
set "DEV_OLLAMA_ENDPOINT="
set "DEV_ENDPOINT_KEY="
set "DEV_MODE_FLAG="

:parse_args
if "%~1"=="" goto :args_done
set "ARG=%~1"
if /I "!ARG!"=="--dev" (
  set "DEV_MODE=1"
) else if /I "!ARG!"=="--dev0" (
  set "DEV_MODE=2"
) else if /I "!ARG!"=="--dev2" (
  set "DEV_MODE=3"
) else if /I "!ARG!"=="--dev20" (
  set "DEV_MODE=4"
) else (
  if "!ARG:~0,2!"=="--" set "ARG=!ARG:~2!"
  if not defined CHAT_MODEL set "CHAT_MODEL=!ARG!"
)
shift
goto :parse_args

:args_done
if "%DEV_MODE%"=="1" (
  set "DEV_ENDPOINT_KEY=COPYLOT_DEV_OLLAMA_ENDPOINT"
  set "DEV_MODE_FLAG=--dev"
) else if "%DEV_MODE%"=="2" (
  set "DEV_ENDPOINT_KEY=COPYLOT_DEV_OLLAMA_ENDPOINT"
  set "DEV_MODE_FLAG=--dev0"
) else if "%DEV_MODE%"=="3" (
  set "DEV_ENDPOINT_KEY=COPYLOT_DEV2_OLLAMA_ENDPOINT"
  set "DEV_MODE_FLAG=--dev2"
) else if "%DEV_MODE%"=="4" (
  set "DEV_ENDPOINT_KEY=COPYLOT_DEV2_OLLAMA_ENDPOINT"
  set "DEV_MODE_FLAG=--dev20"
)

if not "%DEV_MODE%"=="0" (
  set "DEV_CONFIG=%ROOT%dev_ai.local.env"
  if exist "!DEV_CONFIG!" (
    for /f "usebackq tokens=1,* delims==" %%A in ("!DEV_CONFIG!") do (
      if /I "%%~A"=="!DEV_ENDPOINT_KEY!" set "DEV_OLLAMA_ENDPOINT=%%~B"
    )
    if not defined DEV_OLLAMA_ENDPOINT (
      echo Warning: !DEV_MODE_FLAG! requested but !DEV_ENDPOINT_KEY! is missing in "!DEV_CONFIG!".
    )
  ) else (
    echo Warning: !DEV_MODE_FLAG! requested but dev config file not found: "!DEV_CONFIG!"
  )
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

if "%DEV_MODE%"=="1" (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_AI_DEV_MODE=1 && set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=!DEV_OLLAMA_ENDPOINT! && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
) else if "%DEV_MODE%"=="3" (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_AI_DEV_MODE=1 && set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=!DEV_OLLAMA_ENDPOINT! && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
) else if "%DEV_MODE%"=="2" (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=!DEV_OLLAMA_ENDPOINT! && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
) else if "%DEV_MODE%"=="4" (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=!DEV_OLLAMA_ENDPOINT! && set VITE_AI_DEFAULT_OLLAMA_MODEL=llama3.1:8b && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
) else (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
)
timeout /t 2 /nobreak >nul
start "" "http://localhost:%FRONTEND_PORT%"
