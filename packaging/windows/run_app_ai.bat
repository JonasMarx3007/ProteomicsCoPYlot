@echo off
setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI\"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%check_launch_ports.ps1" -BackendPort %BACKEND_PORT% -FrontendPort %FRONTEND_PORT%
if errorlevel 1 exit /b 1
set "CHAT_MODEL="

:parse_args
if "%~1"=="" goto :args_done
set "ARG=%~1"
if "!ARG:~0,2!"=="--" (
  echo Error: unknown option "!ARG!". Supply a model name without a flag.
  exit /b 2
)
if defined CHAT_MODEL (
  echo Error: only one model name is supported.
  exit /b 2
)
set "CHAT_MODEL=!ARG!"
shift
goto :parse_args

:args_done
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

if defined CHAT_MODEL (
  start "Backend (AI)" /D "%ROOT%backend" cmd /k "set COPYLOT_AI_MODE=1 && set COPYLOT_OLLAMA_MODEL=!CHAT_MODEL! && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --workers 1 --host 127.0.0.1 --port %BACKEND_PORT%"
) else (
  start "Backend (AI)" /D "%ROOT%backend" cmd /k "set COPYLOT_AI_MODE=1 && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --workers 1 --host 127.0.0.1 --port %BACKEND_PORT%"
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
  echo Warning: backend on port %BACKEND_PORT% is not ready yet.
)

start "Frontend (AI)" /D "%ROOT%frontend" cmd /k "set VITE_AI_ENABLED=1 && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
timeout /t 2 /nobreak >nul
start "" "http://localhost:%FRONTEND_PORT%"
