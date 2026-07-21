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
if /I "%~1"=="--validate-only" set "VALIDATE_ONLY=1"

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

if "%VALIDATE_ONLY%"=="1" (
  echo Validation successful.
  echo Using dev20 endpoint from dev_ai.local.env
  exit /b 0
)

echo.
echo [1/6] Building ProteomicsCoPYlotAI.exe ...
call :build_frontend analysis 1 "" ""
if errorlevel 1 exit /b 1
call :build_target Tool Skip
if errorlevel 1 exit /b 1
call :copy_output "%DIST_DIR%\ProteomicsCoPYlot.exe" "%DIST_DIR%\ProteomicsCoPYlotAI.exe"
if errorlevel 1 exit /b 1

echo.
echo [2/6] Building ProteomicsCoPYlotAIDev20.exe ...
call :build_frontend analysis 1 "%DEV20_ENDPOINT%" "llama3.1:8b"
if errorlevel 1 exit /b 1
call :build_target Tool Skip
if errorlevel 1 exit /b 1
call :copy_output "%DIST_DIR%\ProteomicsCoPYlot.exe" "%DIST_DIR%\ProteomicsCoPYlotAIDev20.exe"
if errorlevel 1 exit /b 1

echo.
echo [3/6] Building DataViewerAI.exe ...
call :build_frontend viewer 1 "" ""
if errorlevel 1 exit /b 1
call :build_target Viewer Skip
if errorlevel 1 exit /b 1
call :copy_output "%DIST_DIR%\DataViewer.exe" "%DIST_DIR%\DataViewerAI.exe"
if errorlevel 1 exit /b 1

echo.
echo [4/6] Building DataViewerAIDev20.exe ...
call :build_frontend viewer 1 "%DEV20_ENDPOINT%" "llama3.1:8b"
if errorlevel 1 exit /b 1
call :build_target Viewer Skip
if errorlevel 1 exit /b 1
call :copy_output "%DIST_DIR%\DataViewer.exe" "%DIST_DIR%\DataViewerAIDev20.exe"
if errorlevel 1 exit /b 1

echo.
echo [5/6] Building standard ProteomicsCoPYlot.exe ...
call :build_target Tool
if errorlevel 1 exit /b 1

echo.
echo [6/6] Building standard DataViewer.exe ...
call :build_target Viewer
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

:build_target
set "TARGET=%~1"
set "MODE=%~2"
if /I "%MODE%"=="Skip" (
  powershell -ExecutionPolicy Bypass -File "%BUILD_SCRIPT%" -Target %TARGET% -SkipFrontendBuild
) else (
  powershell -ExecutionPolicy Bypass -File "%BUILD_SCRIPT%" -Target %TARGET%
)
if errorlevel 1 (
  echo Error: build_exe_windows.ps1 failed for target %TARGET%.
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

:copy_output
if not exist "%~1" (
  echo Error: source executable not found: %~1
  exit /b 1
)
copy /Y "%~1" "%~2" >nul
if errorlevel 1 (
  echo Error: failed to copy "%~1" to "%~2".
  exit /b 1
)
exit /b 0
