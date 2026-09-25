<#
  ChaiJingXue - one-click stop
  Stops the backend API / backend Worker / web started by web\start.ps1.

  Usage:
    pwsh -File web\stop.ps1
    pwsh -File web\stop.ps1 -ApiPort 8000 -WebPort 3000

  NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads BOM-less .ps1
  using the system ANSI code page).
#>
param(
    [int]$ApiPort = 8000,
    [int]$WebPort = 3000
)

$WebDir = $PSScriptRoot
$Root = Split-Path -Parent $WebDir
$PidFile = Join-Path $Root "var\run\pids.json"

function Write-Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Write-Hint($text) { Write-Host "    $text" -ForegroundColor Yellow }

function Stop-Tree {
    param([int]$ProcessId)
    if (-not $ProcessId) { return $false }
    $before = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $existed = $false
    try {
        if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
            $existed = $true
            & taskkill /PID $ProcessId /T /F > $null 2> $null
            Start-Sleep -Milliseconds 300
            if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
                Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {
        # stopping is best-effort
    }
    $ErrorActionPreference = $before
    return $existed
}

function Get-ListeningPids {
    param([int]$Port)
    $found = @()
    try {
        foreach ($connection in @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
            if ($connection.OwningProcess) { $found += [int]$connection.OwningProcess }
        }
    } catch {
        $found = @()
    }
    if ($found.Count -eq 0) {
        # Constrained / sandboxed hosts may refuse Get-NetTCPConnection (CIM).
        # netstat needs no elevation and is always present on Windows.
        $before = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            foreach ($line in @(& netstat -ano 2> $null)) {
                if ($line -match ("^\s*TCP\s+\S+:" + $Port + "\s+\S+\s+LISTENING\s+(\d+)\s*$")) {
                    $found += [int]$Matches[1]
                }
            }
        } catch {
            $found = @()
        }
        $ErrorActionPreference = $before
    }
    return @($found | Sort-Object -Unique)
}

$stopped = 0

if (Test-Path $PidFile) {
    $recorded = Get-Content $PidFile -Raw | ConvertFrom-Json
    foreach ($entry in @($recorded.api, $recorded.worker, $recorded.web)) {
        if ($entry -and $entry.pid) {
            if (Stop-Tree -ProcessId ([int]$entry.pid)) { Write-Ok "stopped pid=$($entry.pid)"; $stopped++ }
        }
    }
    Remove-Item -Force $PidFile -ErrorAction SilentlyContinue
} else {
    Write-Hint "no var\run\pids.json, falling back to port lookup (netstat)"
}

foreach ($port in @($ApiPort, $WebPort)) {
    foreach ($processId in (Get-ListeningPids -Port $port)) {
        if (Stop-Tree -ProcessId $processId) {
            Write-Ok "stopped pid=$processId on port $port"
            $stopped++
        }
    }
}

if ($stopped -eq 0) {
    Write-Hint "nothing was running"
} else {
    Write-Host ""
    Write-Host "stopped $stopped process(es)." -ForegroundColor Green
}
