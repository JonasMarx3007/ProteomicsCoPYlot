param(
  [Parameter(Mandatory = $true)]
  [string]$OutputPath,
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[A-Za-z0-9_.-]+$')]
  [string]$ExecutableName,
  [Parameter(Mandatory = $true)]
  [string]$ProductName,
  [Parameter(Mandatory = $true)]
  [string]$FileDescription
)

$ErrorActionPreference = "Stop"

$RootDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$PyProjectPath = Join-Path $RootDir "pyproject.toml"
$BackendVersionPath = Join-Path $RootDir "backend\app\app_version.py"
$PackageVersionPath = Join-Path $RootDir "proteomicscopylot\_version.py"

function Read-VersionValue {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Pattern,
    [Parameter(Mandatory = $true)]
    [string]$Label
  )

  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Label version file missing: $Path"
  }

  $match = [regex]::Match(
    (Get-Content -LiteralPath $Path -Raw),
    $Pattern,
    [System.Text.RegularExpressions.RegexOptions]::Multiline
  )
  if (-not $match.Success) {
    throw "Could not read $Label version from $Path"
  }
  return $match.Groups[1].Value
}

function ConvertTo-VersionStringLiteral {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Value
  )

  return $Value.Replace('\', '\\').Replace("'", "\'").Replace("`r", "\r").Replace("`n", "\n")
}

$ProjectVersion = Read-VersionValue `
  -Path $PyProjectPath `
  -Pattern '^\s*version\s*=\s*["'']([^"'']+)["'']\s*$' `
  -Label "project"
$BackendVersion = Read-VersionValue `
  -Path $BackendVersionPath `
  -Pattern '^\s*APP_VERSION\s*=\s*["'']([^"'']+)["'']\s*$' `
  -Label "backend"
$PackageVersion = Read-VersionValue `
  -Path $PackageVersionPath `
  -Pattern '^\s*__version__\s*=\s*["'']([^"'']+)["'']\s*$' `
  -Label "package"

if ($BackendVersion -ne $ProjectVersion -or $PackageVersion -ne $ProjectVersion) {
  throw "Version mismatch: pyproject.toml=$ProjectVersion, backend=$BackendVersion, package=$PackageVersion"
}

$numericMatch = [regex]::Match(
  $ProjectVersion,
  '^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:[-+._]?[0-9A-Za-z.-]+)?$'
)
if (-not $numericMatch.Success) {
  throw "Version '$ProjectVersion' cannot be represented as a Windows four-part file version."
}

$versionParts = @(
  [int]$numericMatch.Groups[1].Value,
  [int]$numericMatch.Groups[2].Value,
  [int]$numericMatch.Groups[3].Value,
  $(if ($numericMatch.Groups[4].Success) { [int]$numericMatch.Groups[4].Value } else { 0 })
)
foreach ($part in $versionParts) {
  if ($part -lt 0 -or $part -gt 65535) {
    throw "Windows file-version components must be between 0 and 65535: $ProjectVersion"
  }
}

$ExecutableFileName = "$ExecutableName.exe"
$FileVersion = $versionParts -join "."
$escapedCompanyName = ConvertTo-VersionStringLiteral "ProteomicsCoPYlot contributors"
$escapedDescription = ConvertTo-VersionStringLiteral $FileDescription
$escapedExecutableName = ConvertTo-VersionStringLiteral $ExecutableName
$escapedExecutableFileName = ConvertTo-VersionStringLiteral $ExecutableFileName
$escapedProductName = ConvertTo-VersionStringLiteral $ProductName
$escapedProjectVersion = ConvertTo-VersionStringLiteral $ProjectVersion
$escapedFileVersion = ConvertTo-VersionStringLiteral $FileVersion

$content = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($versionParts[0]), $($versionParts[1]), $($versionParts[2]), $($versionParts[3])),
    prodvers=($($versionParts[0]), $($versionParts[1]), $($versionParts[2]), $($versionParts[3])),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName', u'$escapedCompanyName'),
          StringStruct(u'FileDescription', u'$escapedDescription'),
          StringStruct(u'FileVersion', u'$escapedFileVersion'),
          StringStruct(u'InternalName', u'$escapedExecutableName'),
          StringStruct(u'LegalCopyright', u'Copyright (c) 2025-2026 Jonas Marx; third-party notices included'),
          StringStruct(u'OriginalFilename', u'$escapedExecutableFileName'),
          StringStruct(u'ProductName', u'$escapedProductName'),
          StringStruct(u'ProductVersion', u'$escapedProjectVersion')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@

$fullOutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $fullOutputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($fullOutputPath, $content, $utf8NoBom)

Write-Host "Generated Windows version metadata for $ExecutableFileName (version $ProjectVersion): $fullOutputPath"
