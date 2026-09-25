# ChaiJingXue - one-command dev launcher (thin wrapper).
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 files
# without a BOM using the system ANSI code page, so non-ASCII literals can
# break parsing. Chinese documentation lives in README.md / web/README.md.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
#   (or double-click web\start.cmd)
#
# All real work happens in web/start.ps1: preflight -> seed -> API(8000)
# -> Worker -> Web(3000) -> readiness probe.

param(
    [ValidateSet('dev', 'prod')]
    [string]$Mode = 'dev',
    [switch]$SkipSeed,
    [switch]$SkipInstall,
    [switch]$SkipBuild,
    [switch]$ForceBuild,
    [switch]$WithSamples,
    [int]$ApiPort = 8000,
    [int]$WebPort = 3000,
    [switch]$NoBrowser,
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root 'web\start.ps1'

if (-not (Test-Path $target)) {
    Write-Host "web\start.ps1 not found. Expected at: $target" -ForegroundColor Red
    exit 1
}

$forward = @{
    Mode        = $Mode
    ApiPort     = $ApiPort
    WebPort     = $WebPort
    SkipSeed    = $SkipSeed
    SkipInstall = $SkipInstall
    SkipBuild   = $SkipBuild
    ForceBuild  = $ForceBuild
    WithSamples = $WithSamples
    NoBrowser   = $NoBrowser
    Verify      = $Verify
}

& $target @forward
exit $LASTEXITCODE
