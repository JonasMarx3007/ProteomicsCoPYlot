param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("Tool", "Viewer")]
  [string]$Target,
  [string]$ViewerProject = "",
  [switch]$SkipFrontendBuild,
  [ValidatePattern('^[A-Za-z0-9_.-]+$')]
  [string]$ExecutableName = "",
  [switch]$Sign,
  [switch]$ValidateOnly
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
# Written by the Vite build (frontend/vite.config.ts); launch.py reads the same file.
$FrontendModeMarker = Join-Path $FrontendDir "dist\build-mode.json"
$SpecDir = Join-Path $RootDir "build\specs"
$ViewerBundleRoot = Join-Path $RootDir "build\viewer_bundle"
$FrontendTargetMode = if ($Target -eq "Viewer") { "viewer" } else { "analysis" }
$ViewerProjectRegex = '^[A-Za-z0-9_.-]{1,128}$'
$VersionInfoScript = Join-Path $PSScriptRoot "new_windows_version_info.ps1"
$SigningScript = Join-Path $PSScriptRoot "sign_windows_executables.ps1"
$ReleaseHelper = Join-Path $RootDir "tools\package_release_licenses.py"

if (-not $ExecutableName) {
  $ExecutableName = if ($Target -eq "Viewer") { "DataViewer" } else { "ProteomicsCoPYlot" }
}

$ProductName = if ($Target -eq "Viewer") {
  "Proteomics CoPYlot Data Viewer"
}
else {
  "Proteomics CoPYlot"
}
$FileDescription = switch ($ExecutableName) {
  "ProteomicsCoPYlot" { "Proteomics CoPYlot" }
  "ProteomicsCoPYlotAI" { "Proteomics CoPYlot (AI)" }
  "DataViewer" { "Proteomics CoPYlot Data Viewer" }
  "DataViewerAI" { "Proteomics CoPYlot Data Viewer (AI)" }
  default { "$ProductName Windows application" }
}
$VersionInfoPath = Join-Path $SpecDir "$ExecutableName.version_info.txt"

if (-not (Test-Path -LiteralPath $VersionInfoScript -PathType Leaf)) {
  throw "Windows version-info generator missing: $VersionInfoScript"
}

& $VersionInfoScript `
  -OutputPath $VersionInfoPath `
  -ExecutableName $ExecutableName `
  -ProductName $ProductName `
  -FileDescription $FileDescription

if ($Sign) {
  if (-not (Test-Path -LiteralPath $SigningScript -PathType Leaf)) {
    throw "Windows signing helper missing: $SigningScript"
  }
  $machineStore = $env:COPYLOT_SIGNING_CERT_MACHINE_STORE -eq "1"
  & $SigningScript -ValidateOnly -MachineCertificateStore:$machineStore
}

if ($ValidateOnly) {
  Write-Host "Validation successful for $ExecutableName.exe. No executable was compiled."
  return
}

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
}

$FrontendIndex = Join-Path $FrontendDir "dist\index.html"
if (-not (Test-Path $FrontendIndex)) {
  throw "Frontend build output missing. Expected: $FrontendIndex"
}

if (-not (Test-Path $FrontendModeMarker)) {
  throw "Frontend mode marker missing. Rebuild frontend without -SkipFrontendBuild."
}

$CurrentFrontendMode = [string]((Get-Content -Path $FrontendModeMarker -Raw | ConvertFrom-Json).appMode)
$CurrentFrontendMode = $CurrentFrontendMode.Trim().ToLowerInvariant()
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
  $LegalDir = Join-Path $RootDir "build\legal\$Name"
  & $PythonExe $ReleaseHelper prepare --legal-dir $LegalDir
  Assert-LastExitCode -Step "Collect release licences and corresponding source"

  $pyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--specpath", $SpecDir,
    "--icon", $IconPath,
    "--name", $Name,
    "--version-file", $VersionInfoPath,
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
  $notebookSources = Get-Content -Path (Join-Path $RootDir "packaging\notebook_sources.txt") |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") }
  foreach ($notebookSource in $notebookSources) {
    $pyInstallerArgs += @("--add-data", "$(Join-Path $BackendDir "app\services\$notebookSource");notebook_sources")
  }
  $notebookDistributions = Get-Content -Path (Join-Path $RootDir "packaging\notebook_distributions.txt") |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") }
  foreach ($notebookDistribution in $notebookDistributions) {
    $pyInstallerArgs += @("--copy-metadata", $notebookDistribution)
  }
  $pyInstallerArgs += @("--add-data", "$(Join-Path $RootDir "proteomicscopylot\notebook_functions.py");notebook_sources")
  # The arithmetic the backend shares with the pip package; app.services.copylot_core loads it from here.
  $pyInstallerArgs += @("--add-data", "$(Join-Path $RootDir "proteomicscopylot\_core.py");notebook_sources")
  $pyInstallerArgs += @("--add-data", "$(Join-Path $RootDir "LICENSE");notebook_sources")
  $pyInstallerArgs += @("--add-data", "$(Join-Path $RootDir "NOTICE");notebook_sources")
  $pyInstallerArgs += @("--add-data", "$LegalDir;legal")
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

  if ($ProjectName -in @("local", "projects")) {
    throw "Private viewer project roots cannot be bundled."
  }

  $sourceDir = Join-Path $RootDir "viewer_data\$ProjectName"
  $configPath = Join-Path $sourceDir "viewer_config.json"
  if (-not (Test-Path $configPath -PathType Leaf)) {
    throw "Public viewer project '$ProjectName' not found or missing viewer_config.json."
  }

  $publicViewerRoot = (Resolve-Path -LiteralPath (Join-Path $RootDir "viewer_data")).Path
  $resolvedSourceDir = (Resolve-Path -LiteralPath $sourceDir).Path
  if ((Split-Path -Parent $resolvedSourceDir) -ne $publicViewerRoot) {
    throw "Viewer project '$ProjectName' must be a direct child of viewer_data."
  }
  $sourceItem = Get-Item -LiteralPath $resolvedSourceDir
  if ($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
    throw "Viewer project '$ProjectName' cannot be a symlink or junction."
  }

  $prefix = "viewer_data/$ProjectName/"
  $trackedFiles = @(& git -C $RootDir ls-files -- "$prefix*")
  Assert-LastExitCode -Step "list tracked viewer project files"
  if ($trackedFiles -notcontains "${prefix}viewer_config.json") {
    throw "Viewer project '$ProjectName' is not a tracked public project."
  }

  $blockedNames = @(
    ".env",
    "tool_access.json",
    "viewer_access.json",
    "viewer_qr_access.json"
  )
  foreach ($relativePath in $trackedFiles) {
    $projectRelative = $relativePath.Substring($prefix.Length)
    $segments = @($projectRelative.ToLowerInvariant() -split "/")
    $leaf = [System.IO.Path]::GetFileName($relativePath).ToLowerInvariant()
    $extension = [System.IO.Path]::GetExtension($leaf).ToLowerInvariant()
    if (
      $segments -contains "local" -or
      $segments -contains "projects" -or
      $leaf -in $blockedNames -or
      $leaf.StartsWith(".env.") -or
      $leaf.Contains(".local.") -or
      $leaf -match "(^|[._-])(credential|secret|password|token|access)([._-]|$)" -or
      $extension -in @(".env", ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".sql", ".dump", ".db", ".sqlite", ".sqlite3")
    ) {
      throw "Tracked private configuration is not allowed in viewer project bundles: $relativePath"
    }
  }

  $buildRoot = (Resolve-Path (Join-Path $RootDir "build")).Path
  $bundleRootFull = [System.IO.Path]::GetFullPath($ViewerBundleRoot)
  if (-not $bundleRootFull.StartsWith("$buildRoot\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Invalid managed viewer bundle directory."
  }
  if (Test-Path $ViewerBundleRoot) {
    Remove-Item -LiteralPath $ViewerBundleRoot -Recurse -Force
  }

  $stagedProject = Join-Path $ViewerBundleRoot $ProjectName
  New-Item -ItemType Directory -Force -Path $stagedProject | Out-Null
  foreach ($relativePath in $trackedFiles) {
    $projectRelative = $relativePath.Substring($prefix.Length)
    $sourcePath = Join-Path $RootDir ($relativePath -replace "/", "\")
    $item = Get-Item -LiteralPath $sourcePath
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
      throw "Viewer project bundle entries must not be links: $relativePath"
    }
    $destination = Join-Path $stagedProject ($projectRelative -replace "/", "\")
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destination
  }

  return @{
    Project = $ProjectName
    SourceDir = $stagedProject
  }
}

if ($ViewerProject -and $Target -ne "Viewer") {
  throw "-ViewerProject can only be used with -Target Viewer."
}

$viewerDataAddData = @(
  "$(Join-Path $RootDir "viewer_config.json");."
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
      Invoke-PyInstallerBuild -Name $ExecutableName -EntryPoint "launch_tool.py" -ViewerDataAddData $viewerDataAddData
    }
    "Viewer" {
      Invoke-PyInstallerBuild -Name $ExecutableName -EntryPoint "launch_viewer.py" -ViewerDataAddData $viewerDataAddData
    }
  }
}
finally {
  Pop-Location
}

$ExecutablePath = Join-Path $RootDir "dist\$ExecutableName.exe"

if ($Sign) {
  & $SigningScript -ExecutablePath $ExecutablePath -MachineCertificateStore:$machineStore
}
& $PythonExe $ReleaseHelper finish --legal-dir (Join-Path $RootDir "build\legal\$ExecutableName") --executable $ExecutablePath
Assert-LastExitCode -Step "Package executable, licences and corresponding source"

Write-Host ""
Write-Host "Build completed."
Write-Host "$Target executable: $ExecutablePath"
