[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Candidate,
    [Parameter(Mandatory = $true)][string]$Current,
    [Parameter(Mandatory = $true)][string]$Previous,
    [Parameter(Mandatory = $true)][string]$Shim,
    [int]$ParentPid = 0
)

$ErrorActionPreference = "Stop"
if ($ParentPid -gt 0) {
    try { Wait-Process -Id $ParentPid -Timeout 120 -ErrorAction SilentlyContinue } catch { }
}
if (-not (Test-Path $Candidate)) { throw "候选版本不存在：$Candidate" }
if (Test-Path $Previous) { Remove-Item -LiteralPath $Previous -Recurse -Force }
if (Test-Path $Current) { Move-Item -LiteralPath $Current -Destination $Previous }
Move-Item -LiteralPath $Candidate -Destination $Current
$exe = Join-Path $Current "skillcheck.exe"
Set-Content -LiteralPath $Shim -Value "@echo off`r`n`"$exe`" %*`r`n" -Encoding ascii

