<#
  ChaiJingXue - one-click local startup (Windows PowerShell)

  Starts the whole stack with a single command:
    1) preflight  (.venv / node / ffmpeg / ffprobe)
    2) init DB + knowledge cards + test accounts (optional demo samples)
    3) start backend API (default 8000) and backend Worker
    4) install web deps if needed, then start web (default 3000)

  Usage:
    pwsh -File web\start.ps1                 # dev mode  (next dev, hot reload)
    pwsh -File web\start.ps1 -Mode prod      # prod mode (next build + next start)
    pwsh -File web\start.ps1 -SkipSeed
    pwsh -File web\start.ps1 -SkipInstall
    pwsh -File web\start.ps1 -ForceBuild
    pwsh -File web\start.ps1 -Verify         # start, health-check, stop (CI)
    pwsh -File web\start.ps1 -NoBrowser
    pwsh -File web\start.ps1 -ShowWindows   # show live service consoles (debug)

  Stop:
    pwsh -File web\stop.ps1

  NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads BOM-less .ps1
  files using the system ANSI code page, so non-ASCII literals can corrupt
  parsing. User-facing Chinese text lives in README.md / the web UI.
#>
param(
    [ValidateSet("dev", "prod")]
    [string]$Mode = "dev",
    [int]$ApiPort = 8000,
    [int]$WebPort = 3000,
    [switch]$SkipSeed,
    [switch]$SkipInstall,
    [switch]$SkipBuild,
    [switch]$ForceBuild,
    [switch]$WithSamples,
    [switch]$Verify,
    [switch]$NoBrowser,
    [switch]$ShowWindows
)

$ErrorActionPreference = "Stop"

$WebDir = $PSScriptRoot
$Root = Split-Path -Parent $WebDir
$BackendDir = Join-Path $Root "backend"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$RunDir = Join-Path $Root "var\run"
$LogDir = Join-Path $RunDir "logs"
$PidFile = Join-Path $RunDir "pids.json"
$ApiUrl = "http://127.0.0.1:$ApiPort"
$WebUrl = "http://127.0.0.1:$WebPort"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# By default every service runs in a HIDDEN console: stdout/stderr already go to
# var\run\logs, so no extra terminal windows clutter the desktop.
# (ffmpeg/ffprobe children inherit this hidden console, so they do not flash either.)
# Use -ShowWindows when you want to watch the raw output live.
$WindowStyle = "Hidden"
if ($ShowWindows) { $WindowStyle = "Normal" }

# Show UTF-8 output from child tools (python/uvicorn print Chinese) correctly.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # non-fatal
}

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "    $text" -ForegroundColor Green }
function Write-Hint($text) { Write-Host "    $text" -ForegroundColor Yellow }
function Write-Err($text) { Write-Host "    $text" -ForegroundColor Red }

function Wait-Http {
    param([string]$Url, [int]$Seconds = 60, [string]$Name = "service")
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        } catch {
            Start-Sleep -Milliseconds 700
        }
    }
    Write-Err "$Name was not ready within $Seconds s : $Url"
    return $false
}

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

function Stop-Recorded {
    if (-not (Test-Path $PidFile)) { return }
    $recorded = Get-Content $PidFile -Raw | ConvertFrom-Json
    foreach ($entry in @($recorded.api, $recorded.worker, $recorded.web)) {
        if ($entry -and $entry.pid) {
            if (Stop-Tree -ProcessId ([int]$entry.pid)) { Write-Ok "stopped pid=$($entry.pid)" }
        }
    }
    Remove-Item -Force $PidFile -ErrorAction SilentlyContinue
}

Write-Step "Preflight"

if (-not (Test-Path $Python)) {
    Write-Err "virtualenv not found: $Python"
    Write-Hint "create it from the project root:"
    Write-Hint "  python -m venv .venv"
    Write-Hint "  .\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt"
    exit 1
}
Write-Ok "python: $Python"

foreach ($tool in @("node", "npm")) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    if (-not $found) { Write-Err "$tool not found, please install Node 20+"; exit 1 }
}
Write-Ok ("node " + (& node -v) + " / npm " + (& npm -v))

$ffmpegOk = [bool](Get-Command ffmpeg -ErrorAction SilentlyContinue)
$ffprobeOk = [bool](Get-Command ffprobe -ErrorAction SilentlyContinue)
if ($ffmpegOk -and $ffprobeOk) {
    Write-Ok "ffmpeg / ffprobe found in PATH"
} else {
    Write-Hint "ffmpeg=$ffmpegOk ffprobe=$ffprobeOk -> media validation will fail with media_toolchain_missing"
}

if (Test-Path $PidFile) {
    Write-Hint "previous run recorded in pids.json, stopping it first"
    Stop-Recorded
}

if (-not $SkipSeed) {
    Write-Step "Init database / knowledge cards / test accounts"
    $env:PYTHONPATH = $BackendDir
    $env:PYTHONIOENCODING = "utf-8"
    Push-Location $BackendDir
    $seedArgs = @("-m", "app.cli", "seed")
    if ($WithSamples) { $seedArgs += "--with-samples" }
    & $Python @seedArgs
    $seedCode = $LASTEXITCODE
    Pop-Location
    if ($seedCode -ne 0) { Write-Hint "seed exited with $seedCode, continuing anyway" } else { Write-Ok "seed done" }
} else {
    Write-Step "Skip seed (-SkipSeed)"
}

Write-Step "Start backend API ($ApiUrl)"
$env:PYTHONPATH = $BackendDir
$apiLog = Join-Path $LogDir "api.log"
$apiErrLog = Join-Path $LogDir "api.err.log"
$apiArgs = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort")
$apiProc = Start-Process -FilePath $Python -ArgumentList $apiArgs -WorkingDirectory $BackendDir -WindowStyle $WindowStyle -PassThru -RedirectStandardOutput $apiLog -RedirectStandardError $apiErrLog
Write-Ok "API pid=$($apiProc.Id)  log: $apiLog"

if (-not (Wait-Http -Url "$ApiUrl/api/v1/healthz" -Seconds 90 -Name "backend API")) {
    Write-Err "see logs: $apiLog / $apiErrLog"
    Stop-Recorded
    exit 1
}
Write-Ok "API ready"

Write-Step "Start backend Worker"
$workerLog = Join-Path $LogDir "worker.log"
$workerErrLog = Join-Path $LogDir "worker.err.log"
$workerArgs = @("-m", "app.worker")
$workerProc = Start-Process -FilePath $Python -ArgumentList $workerArgs -WorkingDirectory $BackendDir -WindowStyle $WindowStyle -PassThru -RedirectStandardOutput $workerLog -RedirectStandardError $workerErrLog
Write-Ok "Worker pid=$($workerProc.Id)  log: $workerLog"

$env:npm_config_cache = Join-Path $Root "var\npmcache"
$env:npm_config_update_notifier = "false"
$env:npm_config_audit = "false"
$env:npm_config_fund = "false"

Push-Location $WebDir

if (-not $SkipInstall) {
    if (-not (Test-Path (Join-Path $WebDir "node_modules\next"))) {
        Write-Step "npm install (npm_config_cache=$env:npm_config_cache)"
        & npm install --no-audit --no-fund
        $installCode = $LASTEXITCODE
        if ($installCode -ne 0) { Write-Err "npm install failed"; Pop-Location; Stop-Recorded; exit 1 }
        Write-Ok "dependencies installed"
    } else {
        Write-Step "node_modules present, skip npm install"
    }
} else {
    Write-Step "Skip npm install (-SkipInstall)"
}

$nextBin = Join-Path $WebDir "node_modules\next\dist\bin\next"
$compat = Join-Path $WebDir "scripts\sandbox-compat.cjs"
$buildId = Join-Path $WebDir ".next\BUILD_ID"

if ($Mode -eq "prod") {
    if ($ForceBuild -or -not (Test-Path $buildId)) {
        if ($SkipBuild) {
            Write-Err ".next\BUILD_ID missing in prod mode while -SkipBuild was given"
            Pop-Location; Stop-Recorded; exit 1
        }
        Write-Step "Build web (npm run build)"
        & npm run build
        $buildCode = $LASTEXITCODE
        if ($buildCode -ne 0) { Write-Err "build failed"; Pop-Location; Stop-Recorded; exit 1 }
        Write-Ok "build done"
    } else {
        Write-Step "build artifact present, skip build (-ForceBuild to rebuild)"
    }
}

Write-Step "Start web ($Mode mode, $WebUrl)"
$webLog = Join-Path $LogDir "web.log"
$webErrLog = Join-Path $LogDir "web.err.log"
$webArgs = @("--require", $compat, $nextBin, "dev", "-p", "$WebPort")
if ($Mode -eq "prod") { $webArgs = @("--require", $compat, $nextBin, "start", "-p", "$WebPort") }
$webProc = Start-Process -FilePath "node" -ArgumentList $webArgs -WorkingDirectory $WebDir -WindowStyle $WindowStyle -PassThru -RedirectStandardOutput $webLog -RedirectStandardError $webErrLog
Write-Ok "Web pid=$($webProc.Id)  log: $webLog"

Pop-Location

if (-not (Wait-Http -Url $WebUrl -Seconds 150 -Name "web")) {
    Write-Err "see logs: $webLog / $webErrLog"
    Stop-Recorded
    exit 1
}
Write-Ok "web ready"

$state = [ordered]@{
    started_at = (Get-Date).ToString("s")
    mode = $Mode
    api = @{ pid = $apiProc.Id; url = $ApiUrl; log = $apiLog }
    worker = @{ pid = $workerProc.Id; log = $workerLog }
    web = @{ pid = $webProc.Id; url = $WebUrl; log = $webLog }
}
$state | ConvertTo-Json -Depth 5 | Set-Content -Path $PidFile -Encoding UTF8

Write-Host ""
Write-Host "ChaiJingXue is up" -ForegroundColor Green
Write-Host "  web       $WebUrl      login: alice / alice-pass-123"
Write-Host "  API docs  $ApiUrl/docs"
Write-Host "  health    $ApiUrl/api/v1/healthz"
Write-Host "  logs      $LogDir   (services run hidden; -ShowWindows to watch live)"
Write-Host "  stop      web\stop.cmd   (or: powershell -File web\stop.ps1)"
Write-Host ""

if ($Verify) {
    Write-Step "-Verify: health checks passed, stopping what we started"
    Stop-Recorded
    Write-Ok "stopped"
    exit 0
}

if (-not $NoBrowser) {
    Start-Process $WebUrl | Out-Null
}
