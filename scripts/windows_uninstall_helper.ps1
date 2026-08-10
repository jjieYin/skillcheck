[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$Paths,
    [Parameter(Mandatory = $true)][string]$PathEntry
)

$ErrorActionPreference = "Stop"
Start-Sleep -Seconds 1
foreach ($path in $Paths) {
    if (Test-Path $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$parts = @($userPath -split ";" | Where-Object { $_ -and $_.TrimEnd("\") -ine $PathEntry.TrimEnd("\") })
[Environment]::SetEnvironmentVariable("Path", ($parts -join ";"), "User")

