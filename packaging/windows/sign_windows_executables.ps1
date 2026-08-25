param(
  [string[]]$ExecutablePath = @(),
  [string]$CertificateThumbprint = $env:COPYLOT_SIGNING_CERT_THUMBPRINT,
  [string]$TimestampUrl = "http://timestamp.digicert.com",
  [string]$SignToolPath = $env:COPYLOT_SIGNTOOL_PATH,
  [switch]$MachineCertificateStore,
  [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

function Assert-LastExitCode {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Step
  )

  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with exit code $LASTEXITCODE."
  }
}

$normalizedThumbprint = ([string]$CertificateThumbprint -replace '\s', '').ToUpperInvariant()
if ($normalizedThumbprint -notmatch '^[A-F0-9]{40}$') {
  throw "Set COPYLOT_SIGNING_CERT_THUMBPRINT to the 40-character thumbprint of a code-signing certificate."
}

$timestampUri = $null
if (
  -not [System.Uri]::TryCreate($TimestampUrl, [System.UriKind]::Absolute, [ref]$timestampUri) -or
  $timestampUri.Scheme -notin @("http", "https")
) {
  throw "TimestampUrl must be an absolute HTTP or HTTPS URL."
}

if ($SignToolPath) {
  if (-not (Test-Path -LiteralPath $SignToolPath -PathType Leaf)) {
    throw "SignTool was not found at COPYLOT_SIGNTOOL_PATH: $SignToolPath"
  }
  $resolvedSignTool = (Resolve-Path -LiteralPath $SignToolPath).Path
}
else {
  $signToolCommand = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if (-not $signToolCommand) {
    throw "signtool.exe was not found. Install the Windows SDK or set COPYLOT_SIGNTOOL_PATH."
  }
  $resolvedSignTool = $signToolCommand.Source
}

$certificateStoreRoot = if ($MachineCertificateStore) { "Cert:\LocalMachine\My" } else { "Cert:\CurrentUser\My" }
$certificatePath = Join-Path $certificateStoreRoot $normalizedThumbprint
if (-not (Test-Path -LiteralPath $certificatePath -PathType Leaf)) {
  throw "Code-signing certificate $normalizedThumbprint was not found in $certificateStoreRoot."
}
$certificate = Get-Item -LiteralPath $certificatePath
if (-not $certificate.HasPrivateKey) {
  throw "Code-signing certificate $normalizedThumbprint does not expose a private key."
}
$now = Get-Date
if ($now -lt $certificate.NotBefore -or $now -gt $certificate.NotAfter) {
  throw "Code-signing certificate $normalizedThumbprint is not currently valid ($($certificate.NotBefore) to $($certificate.NotAfter))."
}
$codeSigningOid = "1.3.6.1.5.5.7.3.3"
if ($certificate.EnhancedKeyUsageList.ObjectId.Value -notcontains $codeSigningOid) {
  throw "Certificate $normalizedThumbprint is not valid for code signing."
}

if ($ValidateOnly) {
  Write-Host "Signing configuration validated for certificate $normalizedThumbprint in $certificateStoreRoot."
  return
}

if ($ExecutablePath.Count -eq 0) {
  throw "At least one -ExecutablePath is required when signing."
}

$resolvedExecutables = foreach ($path in $ExecutablePath) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Executable to sign was not found: $path"
  }
  $resolvedPath = (Resolve-Path -LiteralPath $path).Path
  if ([System.IO.Path]::GetExtension($resolvedPath) -ne ".exe") {
    throw "Only .exe files can be signed by this release helper: $resolvedPath"
  }
  $resolvedPath
}

foreach ($resolvedExecutable in $resolvedExecutables) {
  $signArguments = @("sign")
  if ($MachineCertificateStore) {
    $signArguments += "/sm"
  }
  $signArguments += @(
    "/sha1", $normalizedThumbprint,
    "/fd", "SHA256",
    "/td", "SHA256",
    "/tr", $TimestampUrl,
    "/v",
    $resolvedExecutable
  )

  & $resolvedSignTool @signArguments
  Assert-LastExitCode -Step "sign $resolvedExecutable"

  & $resolvedSignTool verify /pa /all /v $resolvedExecutable
  Assert-LastExitCode -Step "verify signature for $resolvedExecutable"
}

Write-Host "Signed and verified $($resolvedExecutables.Count) executable(s)."
