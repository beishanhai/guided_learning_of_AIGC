# ChaiJingXue - stop everything started by scripts\dev.ps1 / web\start.ps1
#
# NOTE: ASCII-only on purpose (Windows PowerShell 5.1 + system ANSI code page).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\stop.ps1
#        (or double-click web\stop.cmd)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root 'web\stop.ps1'

if (-not (Test-Path $target)) {
    Write-Host "web\stop.ps1 not found. Expected at: $target" -ForegroundColor Red
    exit 1
}

& $target
exit $LASTEXITCODE
