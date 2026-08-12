[CmdletBinding()]
param(
    [string]$Version = "latest",
    [string]$Repository = "jjieYin/skillcheck"
)

$ErrorActionPreference = "Stop"

if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64") {
    throw "当前安装器只支持 Windows x64（AMD64）。"
}

$root = Join-Path $env:LOCALAPPDATA "skillcheck"
$versions = Join-Path $root "versions"
$bin = Join-Path $root "bin"
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("skillcheck-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $temporary | Out-Null

try {
    if ($Version -eq "latest") {
        $release = Invoke-RestMethod "https://api.github.com/repos/$Repository/releases/latest"
        $Version = $release.tag_name.TrimStart("v")
    }
    $assetName = "skillcheck-$Version-windows-x64.zip"
    $baseUrl = "https://github.com/$Repository/releases/download/v$Version"
    # A release asset can be replaced after a failed upload. The version query
    # forces GitHub's CDN to resolve the current asset instead of a stale copy.
    $downloadQuery = "?skillcheck_version=$Version"
    $asset = Join-Path $temporary $assetName
    $manifestFile = Join-Path $temporary "manifest.json"
    Invoke-WebRequest "${baseUrl}/${assetName}${downloadQuery}" -OutFile $asset
    Invoke-WebRequest "${baseUrl}/manifest.json${downloadQuery}" -OutFile $manifestFile

    $manifest = Get-Content $manifestFile -Raw | ConvertFrom-Json
    if ($manifest.asset_name -ne $assetName) { throw "Manifest 与发布文件名不一致。" }
    $actual = (Get-FileHash $asset -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $manifest.sha256.ToLowerInvariant()) { throw "SHA-256 校验失败。" }

    $versionDir = Join-Path $versions $Version
    if (-not (Test-Path $versionDir)) {
        $unpack = Join-Path $temporary "unpack"
        Expand-Archive $asset -DestinationPath $unpack
        New-Item -ItemType Directory -Force -Path $versions | Out-Null
        Move-Item $unpack $versionDir
    }
    $executable = Join-Path $versionDir "skillcheck.exe"
    if (-not (Test-Path $executable)) { throw "发布包缺少 skillcheck.exe。" }

    $versionOutput = (& $executable version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "skillcheck $Version(?:\s|$)") {
        throw "版本冒烟检查失败：期望 skillcheck $Version，实际 $versionOutput"
    }
    # Doctor checks the user's existing state, so a stale or incomplete
    # catalog must not prevent the release itself from being installed.
    $doctorExitCode = 0
    try {
        & $executable doctor --json | Out-Null
        $doctorExitCode = $LASTEXITCODE
    } catch {
        # A diagnostic process failure is advisory here; the version smoke
        # check above already proved that the executable can start.
        $doctorExitCode = 2
    }
    if ($doctorExitCode -gt 1) {
        Write-Warning "现有 Skillcheck 状态需要迁移或修复；安装继续。安装完成后请运行 skillcheck doctor，必要时运行 skillcheck init。"
    }
    if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
        & $executable install
        if ($LASTEXITCODE -gt 2) { throw "Agent install 冒烟检查失败。" }
    } else {
        Write-Host "Release installed. Run 'skillcheck install' in an interactive terminal to choose Agent targets."
    }

    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $shim = Join-Path $bin "skillcheck.cmd"
    $content = "@echo off`r`n`"$executable`" %*`r`n"
    if (-not (Test-Path $shim) -or (Get-Content $shim -Raw) -ne $content) {
        Set-Content -Path $shim -Value $content -Encoding ascii
    }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($userPath -split ";" | Where-Object { $_ })
    if (-not ($parts | Where-Object { $_.TrimEnd("\") -ieq $bin.TrimEnd("\") })) {
        [Environment]::SetEnvironmentVariable("Path", (($parts + $bin) -join ";"), "User")
    }
    Write-Host "skillcheck $Version 已安装到 $bin"
}
finally {
    if (Test-Path $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
