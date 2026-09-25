# ChaiJingXue - run the backend test suite.
#
# NOTE: ASCII-only on purpose (Windows PowerShell 5.1 + system ANSI code page).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\test.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root 'backend')

$env:PYTHONPATH = '.'
$env:PYTHONIOENCODING = 'utf-8'

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host "Missing .venv. Create it first (see README.md)." -ForegroundColor Red
    exit 1
}

# -p no:cacheprovider: pytest writes its cache via a 0o700 temp dir, which some
# sandboxed/CI environments refuse to write into.
& $python -m pytest tests -q -p no:cacheprovider
exit $LASTEXITCODE
