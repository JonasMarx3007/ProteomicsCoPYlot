@echo off
setlocal EnableDelayedExpansion
set "ROOT=%~dp0"

set "BACKEND_PORT=8001"
set "FRONTEND_PORT=5174"
set "BACKEND_WAIT_SECONDS=%COPYLOT_WAIT_FOR_BACKEND_SECONDS%"
if "%BACKEND_WAIT_SECONDS%"=="" set "BACKEND_WAIT_SECONDS=20"
set "CHAT_MODEL="
set "DEV_MODE=0"
set "DEV_OLLAMA_ENDPOINT="
set "DEV_ENDPOINT_KEY="
set "DEV_MODE_FLAG="
set "VIEWER_PROJECT="
if exist "%ROOT%viewer_config.local.json" (
  set "VIEWER_CONFIG=%ROOT%viewer_config.local.json"
) else (
  set "VIEWER_CONFIG=%ROOT%viewer_config.json"
)

:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--dev" (
  set "DEV_MODE=1"
  shift
  goto :parse_args
)
if /I "%~1"=="--dev0" (
  set "DEV_MODE=2"
  shift
  goto :parse_args
)
if /I "%~1"=="--dev2" (
  set "DEV_MODE=3"
  shift
  goto :parse_args
)
if /I "%~1"=="--dev20" (
  set "DEV_MODE=4"
  shift
  goto :parse_args
)
if /I "%~1"=="--project" (
  if "%~2"=="" (
    echo Error: --project requires a project name.
    exit /b 1
  )
  set "VIEWER_PROJECT=%~2"
  shift
  shift
  goto :parse_args
)
set "ARG=%~1"
if /I "!ARG:~0,10!"=="--project=" (
  set "VIEWER_PROJECT=!ARG:~10!"
  shift
  goto :parse_args
)
if /I "%~1"=="--model" (
  if "%~2"=="" (
    echo Error: --model requires a model name.
    exit /b 1
  )
  set "CHAT_MODEL=%~2"
  shift
  shift
  goto :parse_args
)
set "ARG=%~1"
if /I "!ARG:~0,8!"=="--model=" (
  set "CHAT_MODEL=!ARG:~8!"
  shift
  goto :parse_args
)

set "ARG=%~1"
if "!ARG:~0,2!"=="--" (
  set "CANDIDATE=!ARG:~2!"
  call :viewer_project_exists "!CANDIDATE!"
  if "!PROJECT_FOUND!"=="1" (
    set "VIEWER_PROJECT=!CANDIDATE!"
    shift
    goto :parse_args
  )
  set "ARG=!CANDIDATE!"
)

if not defined CHAT_MODEL set "CHAT_MODEL=!ARG!"
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

"%ROOT%backend\.venv\Scripts\python.exe" --version >nul 2>&1
if errorlevel 1 (
  echo Error: backend Python runtime is not executable:
  echo   %ROOT%backend\.venv\Scripts\python.exe
  echo Recreate backend\.venv or fix local Python permissions, then run again.
  exit /b 1
)

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
  echo Starting viewer AI backend on port %BACKEND_PORT%...
  start "Backend (Viewer AI)" /D "%ROOT%backend" cmd /k "set COPYLOT_VIEWER_MODE=1 && set COPYLOT_VIEWER_PORTAL_ENABLED=0 && set COPYLOT_VIEWER_INCLUDE_EMPTY_PACKAGES=1 && set COPYLOT_SESSION_ISOLATION=0 && set COPYLOT_RESET_ON_BROWSER_LOAD=0 && set COPYLOT_VIEWER_PROJECT=%VIEWER_PROJECT% && set COPYLOT_VIEWER_CONFIG=%VIEWER_CONFIG% && set COPYLOT_AI_MODE=1 && set COPYLOT_OLLAMA_MODEL=!CHAT_MODEL! && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
) else (
  echo Starting viewer AI backend on port %BACKEND_PORT%...
  start "Backend (Viewer AI)" /D "%ROOT%backend" cmd /k "set COPYLOT_VIEWER_MODE=1 && set COPYLOT_VIEWER_PORTAL_ENABLED=0 && set COPYLOT_VIEWER_INCLUDE_EMPTY_PACKAGES=1 && set COPYLOT_SESSION_ISOLATION=0 && set COPYLOT_RESET_ON_BROWSER_LOAD=0 && set COPYLOT_VIEWER_PROJECT=%VIEWER_PROJECT% && set COPYLOT_VIEWER_CONFIG=%VIEWER_CONFIG% && set COPYLOT_AI_MODE=1 && ""%ROOT%backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
)

set "BACKEND_READY=1"
if %BACKEND_WAIT_SECONDS% GTR 0 (
  set "BACKEND_READY=0"
  for /l %%i in (1,1,%BACKEND_WAIT_SECONDS%) do (
    powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %BACKEND_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
      set "BACKEND_READY=1"
      goto :backend_ready
    )
    timeout /t 1 /nobreak >nul
  )
)

:backend_ready
if "%BACKEND_READY%"=="0" (
  echo Error: viewer backend on port %BACKEND_PORT% did not become ready within %BACKEND_WAIT_SECONDS%s.
  echo Check the "Backend (Viewer AI)" terminal window for the real startup error.
  exit /b 1
)

if "%DEV_MODE%"=="1" (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_VIEWER_PORTAL_AUTH=0 && set VITE_RESET_ON_BROWSER_LOAD=0 && set VITE_AI_DEV_MODE=1 && set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=!DEV_OLLAMA_ENDPOINT! && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
) else if "%DEV_MODE%"=="3" (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_VIEWER_PORTAL_AUTH=0 && set VITE_RESET_ON_BROWSER_LOAD=0 && set VITE_AI_DEV_MODE=1 && set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=!DEV_OLLAMA_ENDPOINT! && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
) else if "%DEV_MODE%"=="2" (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_VIEWER_PORTAL_AUTH=0 && set VITE_RESET_ON_BROWSER_LOAD=0 && set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=!DEV_OLLAMA_ENDPOINT! && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
) else if "%DEV_MODE%"=="4" (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_VIEWER_PORTAL_AUTH=0 && set VITE_RESET_ON_BROWSER_LOAD=0 && set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=!DEV_OLLAMA_ENDPOINT! && set VITE_AI_DEFAULT_OLLAMA_MODEL=llama3.1:8b && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
) else (
  start "Frontend (Viewer AI)" /D "%ROOT%frontend" cmd /k "set VITE_APP_MODE=viewer && set VITE_AI_ENABLED=1 && set VITE_VIEWER_PORTAL_AUTH=0 && set VITE_RESET_ON_BROWSER_LOAD=0 && set VITE_PROXY_TARGET=http://127.0.0.1:%BACKEND_PORT% && npm run dev -- --port %FRONTEND_PORT%"
)
timeout /t 2 /nobreak >nul
start "" "http://localhost:%FRONTEND_PORT%"

goto :eof

:viewer_project_exists
setlocal
set "PROJECT=%~1"
set "FOUND=0"
if exist "%ROOT%viewer_data\%PROJECT%\viewer_config.local.json" set "FOUND=1"
if exist "%ROOT%viewer_data\%PROJECT%\viewer_config.json" set "FOUND=1"
if exist "%ROOT%viewer_data\projects\%PROJECT%\viewer_config.local.json" set "FOUND=1"
if exist "%ROOT%viewer_data\projects\%PROJECT%\viewer_config.json" set "FOUND=1"
endlocal & set "PROJECT_FOUND=%FOUND%"
exit /b 0
