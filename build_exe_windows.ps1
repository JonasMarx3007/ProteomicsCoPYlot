param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("Tool", "Viewer")]
  [string]$Target,
  [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
$IconPath = Join-Path $RootDir "favicon.ico"
$FrontendModeMarker = Join-Path $FrontendDir "dist\.copylot_mode.txt"
$FrontendTargetMode = if ($Target -eq "Viewer") { "viewer" } else { "analysis" }

function Assert-LastExitCode {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Step
  )

  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with exit code $LASTEXITCODE."
  }
}

if (-not (Test-Path $PythonExe)) {
  throw "Backend virtualenv not found. Expected: $PythonExe"
}

if (-not (Test-Path $IconPath)) {
  throw "Application icon missing. Expected: $IconPath"
}

if (-not $SkipFrontendBuild) {
  Push-Location $FrontendDir
  try {
    cmd /c npm install
    Assert-LastExitCode -Step "npm install"
    if ($FrontendTargetMode -eq "viewer") {
      cmd /c "set VITE_APP_MODE=viewer&& npm run build"
      Assert-LastExitCode -Step "frontend build (viewer)"
    }
    else {
      cmd /c "set VITE_APP_MODE=analysis&& npm run build"
      Assert-LastExitCode -Step "frontend build (analysis)"
    }
  }
  finally {
    Pop-Location
  }

  Set-Content -Path $FrontendModeMarker -Value $FrontendTargetMode -NoNewline
}

$FrontendIndex = Join-Path $FrontendDir "dist\index.html"
if (-not (Test-Path $FrontendIndex)) {
  throw "Frontend build output missing. Expected: $FrontendIndex"
}

if (-not (Test-Path $FrontendModeMarker)) {
  throw "Frontend mode marker missing. Rebuild frontend without -SkipFrontendBuild."
}

$CurrentFrontendMode = (Get-Content -Path $FrontendModeMarker -Raw).Trim().ToLowerInvariant()
if ($CurrentFrontendMode -ne $FrontendTargetMode) {
  throw "Frontend dist was built for mode '$CurrentFrontendMode' but target '$Target' requires '$FrontendTargetMode'. Rebuild without -SkipFrontendBuild."
}

& $PythonExe -m pip install --upgrade pip
Assert-LastExitCode -Step "pip upgrade"
& $PythonExe -m pip install pyinstaller
Assert-LastExitCode -Step "install pyinstaller"

function Invoke-PyInstallerBuild {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [Parameter(Mandatory = $true)]
    [string]$EntryPoint
  )

  if (-not (Test-Path (Join-Path $RootDir $EntryPoint))) {
    throw "Entry point missing: $EntryPoint"
  }

  & $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --icon $IconPath `
    --name $Name `
    --paths "backend" `
    --hidden-import "uvicorn.logging" `
    --hidden-import "uvicorn.loops.auto" `
    --hidden-import "uvicorn.protocols.http.auto" `
    --hidden-import "uvicorn.protocols.websockets.auto" `
    --hidden-import "uvicorn.lifespan.on" `
    --collect-all "fastapi" `
    --collect-all "starlette" `
    --collect-all "uvicorn" `
    --collect-all "pandas" `
    --collect-all "numpy" `
    --collect-all "scipy" `
    --collect-all "matplotlib" `
    --collect-all "seaborn" `
    --collect-all "plotly" `
    --collect-all "pyarrow" `
    --collect-all "openpyxl" `
    --add-data "frontend\dist;frontend_dist" `
    --add-data "data\db;data\db" `
    --add-data "viewer_config.json;." `
    --add-data "viewer_data;viewer_data" `
    $EntryPoint
  Assert-LastExitCode -Step "PyInstaller build ($Name)"
}

Push-Location $RootDir
try {
  switch ($Target) {
    "Tool" {
      Invoke-PyInstallerBuild -Name "ProteomicsCoPYlot" -EntryPoint "launch_tool.py"
    }
    "Viewer" {
      Invoke-PyInstallerBuild -Name "DataViewer" -EntryPoint "launch_viewer.py"
    }
  }
}
finally {
  Pop-Location
}

Write-Host ""
Write-Host "Build completed."
if ($Target -eq "Tool") {
  Write-Host "Tool executable: $RootDir\dist\ProteomicsCoPYlot.exe"
}
if ($Target -eq "Viewer") {
  Write-Host "Viewer executable: $RootDir\dist\DataViewer.exe"
}
