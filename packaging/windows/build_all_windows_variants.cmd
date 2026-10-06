@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT=%%~fI"
set "BUILD_SCRIPT=%SCRIPT_DIR%build_exe_windows.ps1"
set "FRONTEND_DIR=%ROOT%\frontend"
set "DIST_DIR=%ROOT%\dist"
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

if "%VALIDATE_ONLY%"=="1" goto validate_only
if "%SIGN_OUTPUTS%"=="1" call :validate_target Tool ProteomicsCoPYlot
if errorlevel 1 exit /b 1

echo.
echo [1/4] Building ProteomicsCoPYlotAI.exe ...
call :build_frontend analysis 1
if errorlevel 1 exit /b 1
call :build_target Tool Skip ProteomicsCoPYlotAI
if errorlevel 1 exit /b 1

echo.
echo [2/4] Building DataViewerAI.exe ...
call :build_frontend viewer 1
if errorlevel 1 exit /b 1
call :build_target Viewer Skip DataViewerAI
if errorlevel 1 exit /b 1

echo.
echo [3/4] Building standard ProteomicsCoPYlot.exe ...
call :build_target Tool Build ProteomicsCoPYlot
if errorlevel 1 exit /b 1

echo.
echo [4/4] Building standard DataViewer.exe ...
call :build_target Viewer Build DataViewer
if errorlevel 1 exit /b 1

echo.
echo Build completed. Outputs:
for %%F in (
  ProteomicsCoPYlot.exe
  ProteomicsCoPYlotAI.exe
  DataViewer.exe
  DataViewerAI.exe
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
call :validate_target Viewer DataViewer
if errorlevel 1 exit /b 1
call :validate_target Viewer DataViewerAI
if errorlevel 1 exit /b 1
echo Validation successful. No executables were compiled.
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
pushd "%FRONTEND_DIR%" >nul
if errorlevel 1 (
  echo Error: failed to enter "%FRONTEND_DIR%".
  endlocal & exit /b 1
)

cmd /c "set VITE_APP_MODE=%MODE%&& set VITE_AI_ENABLED=%AI_ENABLED%&& npm run build"
if errorlevel 1 (
  popd >nul
  echo Error: frontend build failed for mode %MODE%.
  endlocal & exit /b 1
)

popd >nul
endlocal & exit /b 0
