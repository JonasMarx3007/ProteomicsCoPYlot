@echo off
set "ROOT=%~dp0"

set "BACKEND_PORT=8001"
set "FRONTEND_PORT=5174"
set "VIEWER_PROJECT="
set "VIEWER_CONFIG=%ROOT%viewer_config.json"

:parse_args
if "%~1"=="" goto :args_done
set "ARG=%~1"
if /I "!ARG!"=="--project" (
  shift
  if "%~1"=="" (
    echo Error: --project requires a project name.
    exit /b 1
  )
  set "VIEWER_PROJECT=%~1"
) else if /I "!ARG:~0,10!"=="--project=" (
  set "VIEWER_PROJECT=!ARG:~10!"
) else if "!ARG:~0,2!"=="--" (
  if not defined VIEWER_PROJECT set "VIEWER_PROJECT=!ARG:~2!"
) else (
  if not defined VIEWER_PROJECT set "VIEWER_PROJECT=!ARG!"
)
shift
goto :parse_args

:args_done
if defined VIEWER_PROJECT (
  if exist "%ROOT%viewer_data\%VIEWER_PROJECT%\viewer_config.local.json" (
    set "VIEWER_CONFIG=%ROOT%viewer_data\%VIEWER_PROJECT%\viewer_config.local.json"
  ) else if exist "%ROOT%viewer_data\%VIEWER_PROJECT%\viewer_config.json" (
    set "VIEWER_CONFIG=%ROOT%viewer_data\%VIEWER_PROJECT%\viewer_config.json"
  ) else if exist "%ROOT%viewer_data\projects\%VIEWER_PROJECT%\viewer_config.local.json" (
    set "VIEWER_CONFIG=%ROOT%viewer_data\projects\%VIEWER_PROJECT%\viewer_config.local.json"
  ) else if exist "%ROOT%viewer_data\projects\%VIEWER_PROJECT%\viewer_config.json" (
    set "VIEWER_CONFIG=%ROOT%viewer_data\projects\%VIEWER_PROJECT%\viewer_config.json"
  ) else (
    echo Viewer project "%VIEWER_PROJECT%" not found or missing viewer_config.json.
    echo Expected one of:
    echo   %ROOT%viewer_data\%VIEWER_PROJECT%\viewer_config.json
    echo   %ROOT%viewer_data\projects\%VIEWER_PROJECT%\viewer_config.json
    exit /b 1
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

start "Backend (Viewer)" /D "%ROOT%backend" cmd /k "set COPYLOT_VIEWER_MODE=1 && set COPYLOT_VIEWER_PROJECT=%VIEWER_PROJECT% && set COPYLOT_VIEWER_CONFIG=%VIEWER_CONFIG% && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"

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

start "Frontend (Viewer)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
timeout /t 2 /nobreak >nul
start "" "http://localhost:%FRONTEND_PORT%"
