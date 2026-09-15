param(
  [Parameter(Mandatory = $true)]
  [ValidateRange(1, 65535)]
  [int]$BackendPort,
  [Parameter(Mandatory = $true)]
  [ValidateRange(1, 65535)]
  [int]$FrontendPort
)

$ErrorActionPreference = "Stop"
try {
  $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
  $occupied = @($listeners | Where-Object { $_.Port -in @($BackendPort, $FrontendPort) } | Select-Object -ExpandProperty Port -Unique)
  if ($occupied.Count -gt 0) {
    Write-Host "Cannot start CoPYlot: port(s) $($occupied -join ', ') are already in use."
    Write-Host "Close the existing app yourself, or use launch.py with a different --port."
    Write-Host "No existing processes were stopped."
    exit 1
  }
}
catch {
  Write-Host "Cannot verify startup ports. No application was started."
  exit 1
}
exit 0
