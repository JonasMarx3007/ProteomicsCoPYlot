@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "BUILD_SCRIPT=%SCRIPT_DIR%build_exe_windows.ps1"
set "FRONTEND_DIR=%ROOT%\frontend"
set "DIST_DIR=%ROOT%\dist"
set "DEV_CONFIG=%ROOT%\local\dev_ai.local.env"
if not exist "%DEV_CONFIG%" set "DEV_CONFIG=%ROOT%\dev_ai.local.env"
set "DEV20_ENDPOINT="
set "VALIDATE_ONLY=0"
set "SIGN_OUTPUTS=0"

:parse_args
if "%~1"=="" goto args_parsed
if /I "%~1"=="--validate-only" (
  set "VALIDATE_ONLY=1"
) else if /I "%~1"=="--sign" (
  set "SIGN_OUTPUTS=1"
) else (
  echo Error: unknown option "%~1". Supported options: --validate-only, --sign.
  exit /b 2
)
shift
goto parse_args

:args_parsed

if not exist "%BUILD_SCRIPT%" (
  echo Error: build_exe_windows.ps1 not found at "%BUILD_SCRIPT%".
  exit /b 1
)

if not exist "%DEV_CONFIG%" (
  echo Error: dev config not found: "%DEV_CONFIG%".
  exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%A in ("%DEV_CONFIG%") do (
  if /I "%%~A"=="COPYLOT_DEV2_OLLAMA_ENDPOINT" set "DEV20_ENDPOINT=%%~B"
)

if not defined DEV20_ENDPOINT (
  echo Error: COPYLOT_DEV2_OLLAMA_ENDPOINT missing in "%DEV_CONFIG%".
  exit /b 1
)

if "%VALIDATE_ONLY%"=="1" goto validate_only
if "%SIGN_OUTPUTS%"=="1" call :validate_target Tool ProteomicsCoPYlot
if errorlevel 1 exit /b 1

echo.
echo [1/6] Building ProteomicsCoPYlotAI.exe ...
call :build_frontend analysis 1 "" ""
if errorlevel 1 exit /b 1
call :build_target Tool Skip ProteomicsCoPYlotAI
if errorlevel 1 exit /b 1

echo.
echo [2/6] Building ProteomicsCoPYlotAIDev20.exe ...
call :build_frontend analysis 1 "%DEV20_ENDPOINT%" "llama3.1:8b"
if errorlevel 1 exit /b 1
call :build_target Tool Skip ProteomicsCoPYlotAIDev20
if errorlevel 1 exit /b 1

echo.
echo [3/6] Building DataViewerAI.exe ...
call :build_frontend viewer 1 "" ""
if errorlevel 1 exit /b 1
call :build_target Viewer Skip DataViewerAI
if errorlevel 1 exit /b 1

echo.
echo [4/6] Building DataViewerAIDev20.exe ...
call :build_frontend viewer 1 "%DEV20_ENDPOINT%" "llama3.1:8b"
if errorlevel 1 exit /b 1
call :build_target Viewer Skip DataViewerAIDev20
if errorlevel 1 exit /b 1

echo.
echo [5/6] Building standard ProteomicsCoPYlot.exe ...
call :build_target Tool Build ProteomicsCoPYlot
if errorlevel 1 exit /b 1

echo.
echo [6/6] Building standard DataViewer.exe ...
call :build_target Viewer Build DataViewer
if errorlevel 1 exit /b 1

echo.
echo Build completed. Outputs:
for %%F in (
  ProteomicsCoPYlot.exe
  ProteomicsCoPYlotAI.exe
  ProteomicsCoPYlotAIDev20.exe
  DataViewer.exe
  DataViewerAI.exe
  DataViewerAIDev20.exe
) do (
  if exist "%DIST_DIR%\%%F" (
    echo   %DIST_DIR%\%%F
  ) else (
    echo   MISSING: %DIST_DIR%\%%F
  )
)

exit /b 0

:validate_only
call :validate_target Tool ProteomicsCoPYlot
if errorlevel 1 exit /b 1
call :validate_target Tool ProteomicsCoPYlotAI
if errorlevel 1 exit /b 1
call :validate_target Tool ProteomicsCoPYlotAIDev20
if errorlevel 1 exit /b 1
call :validate_target Viewer DataViewer
if errorlevel 1 exit /b 1
call :validate_target Viewer DataViewerAI
if errorlevel 1 exit /b 1
call :validate_target Viewer DataViewerAIDev20
if errorlevel 1 exit /b 1
echo Validation successful. No executables were compiled.
echo Using dev20 endpoint from dev_ai.local.env
exit /b 0

:build_target
set "TARGET=%~1"
set "MODE=%~2"
set "OUTPUT_NAME=%~3"
set "SIGN_ARG="
if "%SIGN_OUTPUTS%"=="1" set "SIGN_ARG=-Sign"
if /I "%MODE%"=="Skip" (
  powershell -ExecutionPolicy Bypass -File "%BUILD_SCRIPT%" -Target %TARGET% -ExecutableName "%OUTPUT_NAME%" -SkipFrontendBuild !SIGN_ARG!
) else (
  powershell -ExecutionPolicy Bypass -File "%BUILD_SCRIPT%" -Target %TARGET% -ExecutableName "%OUTPUT_NAME%" !SIGN_ARG!
)
if errorlevel 1 (
  echo Error: build_exe_windows.ps1 failed for target %TARGET%.
  exit /b 1
)
exit /b 0

:validate_target
set "VALIDATE_SIGN_ARG="
if "%SIGN_OUTPUTS%"=="1" set "VALIDATE_SIGN_ARG=-Sign"
powershell -ExecutionPolicy Bypass -File "%BUILD_SCRIPT%" -Target %~1 -ExecutableName "%~2" -ValidateOnly !VALIDATE_SIGN_ARG!
if errorlevel 1 (
  echo Error: validation failed for %~2.exe.
  exit /b 1
)
exit /b 0

:build_frontend
setlocal EnableDelayedExpansion
set "MODE=%~1"
set "AI_ENABLED=%~2"
set "ENDPOINT=%~3"
set "MODEL=%~4"
set "ENDPOINT_PART="
set "MODEL_PART="
if defined ENDPOINT set "ENDPOINT_PART=&& set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=%ENDPOINT%"
if defined MODEL set "MODEL_PART=&& set VITE_AI_DEFAULT_OLLAMA_MODEL=%MODEL%"

pushd "%FRONTEND_DIR%" >nul
if errorlevel 1 (
  echo Error: failed to enter "%FRONTEND_DIR%".
  endlocal & exit /b 1
)

cmd /c "set VITE_APP_MODE=%MODE%&& set VITE_AI_ENABLED=%AI_ENABLED%!ENDPOINT_PART!!MODEL_PART!&& npm run build"
if errorlevel 1 (
  popd >nul
  echo Error: frontend build failed for mode %MODE%.
  endlocal & exit /b 1
)

powershell -NoProfile -Command "$path = [System.IO.Path]::Combine('%FRONTEND_DIR%','dist','.copylot_mode.txt'); Set-Content -Path $path -Value '%MODE%' -NoNewline"
if errorlevel 1 (
  popd >nul
  echo Error: failed to write frontend mode marker.
  endlocal & exit /b 1
)

popd >nul
endlocal & exit /b 0
