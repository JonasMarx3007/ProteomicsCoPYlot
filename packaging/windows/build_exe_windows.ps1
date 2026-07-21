param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("Tool", "Viewer")]
  [string]$Target,
  [string]$ViewerProject = "",
  [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$FrontendDistDir = Join-Path $FrontendDir "dist"
$DataDbDir = Join-Path $RootDir "data\db"
$DataReportDir = Join-Path $RootDir "data\report"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
$IconPath = Join-Path $FrontendDir "public\favicon.ico"
$FrontendModeMarker = Join-Path $FrontendDir "dist\.copylot_mode.txt"
$SpecDir = Join-Path $RootDir "build\specs"
$FrontendTargetMode = if ($Target -eq "Viewer") { "viewer" } else { "analysis" }
$ViewerProjectRegex = '^[A-Za-z0-9_.-]{1,128}$'

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

New-Item -ItemType Directory -Force -Path $SpecDir | Out-Null

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
    [string]$EntryPoint,
    [Parameter(Mandatory = $true)]
    [string[]]$ViewerDataAddData
  )

  if (-not (Test-Path (Join-Path $RootDir $EntryPoint))) {
    throw "Entry point missing: $EntryPoint"
  }

  $pyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--specpath", $SpecDir,
    "--icon", $IconPath,
    "--name", $Name,
    "--paths", $BackendDir,
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespan.on",
    "--collect-all", "fastapi",
    "--collect-all", "starlette",
    "--collect-all", "uvicorn",
    "--collect-all", "pandas",
    "--collect-all", "numpy",
    "--collect-all", "scipy",
    "--collect-all", "sklearn",
    "--collect-all", "umap",
    "--collect-all", "matplotlib",
    "--collect-all", "seaborn",
    "--collect-all", "plotly",
    "--collect-all", "pyarrow",
    "--collect-all", "openpyxl",
    "--add-data", "$FrontendDistDir;frontend_dist",
    "--add-data", "$DataDbDir;data\db",
    "--add-data", "$DataReportDir;data\report",
    "--add-data", "$(Join-Path $RootDir "proteomicscopylot\example_data");proteomicscopylot\example_data"
  )

  foreach ($viewerDataSpec in $ViewerDataAddData) {
    $pyInstallerArgs += @("--add-data", $viewerDataSpec)
  }
  $pyInstallerArgs += $EntryPoint

  & $PythonExe -m PyInstaller @pyInstallerArgs
  Assert-LastExitCode -Step "PyInstaller build ($Name)"
}

function Resolve-ViewerProjectBundle {
  param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectName
  )

  if ($ProjectName -notmatch $ViewerProjectRegex) {
    throw "Invalid -ViewerProject '$ProjectName'. Allowed characters: letters, numbers, dot, underscore, hyphen."
  }

  $candidates = @(
    (Join-Path $RootDir "viewer_data\local\$ProjectName"),
    (Join-Path $RootDir "viewer_data\$ProjectName"),
    (Join-Path $RootDir "viewer_data\projects\$ProjectName")
  )

  foreach ($candidate in $candidates) {
    if (-not (Test-Path $candidate -PathType Container)) {
      continue
    }
    $localConfig = Join-Path $candidate "viewer_config.local.json"
    $defaultConfig = Join-Path $candidate "viewer_config.json"
    if ((Test-Path $localConfig -PathType Leaf) -or (Test-Path $defaultConfig -PathType Leaf)) {
      return @{
        Project = $ProjectName
        SourceDir = $candidate
      }
    }
  }

  throw "Viewer project '$ProjectName' not found or missing viewer_config.json under viewer_data."
}

if ($ViewerProject -and $Target -ne "Viewer") {
  throw "-ViewerProject can only be used with -Target Viewer."
}

$viewerDataAddData = @(
  "$(Join-Path $RootDir "viewer_config.json");.",
  "$(Join-Path $RootDir "viewer_data");viewer_data"
)
if ($Target -eq "Viewer" -and $ViewerProject) {
  $viewerProjectBundle = Resolve-ViewerProjectBundle -ProjectName $ViewerProject
  $viewerSourceDir = [string]$viewerProjectBundle.SourceDir
  $viewerDestDir = "viewer_data\$ViewerProject"
  $viewerDataAddData = @("$viewerSourceDir;$viewerDestDir")
  Write-Host "Bundling viewer project '$ViewerProject' from $viewerSourceDir"
}

Push-Location $RootDir
try {
  switch ($Target) {
    "Tool" {
      Invoke-PyInstallerBuild -Name "ProteomicsCoPYlot" -EntryPoint "launch_tool.py" -ViewerDataAddData $viewerDataAddData
    }
    "Viewer" {
      Invoke-PyInstallerBuild -Name "DataViewer" -EntryPoint "launch_viewer.py" -ViewerDataAddData $viewerDataAddData
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
