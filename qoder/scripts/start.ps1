# PaperDesk 2.0 launcher (Windows PowerShell)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start.ps1 [-SkipSeed]
param(
    [switch]$SkipSeed
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[1/6] creating .venv ..."
    python -m venv .venv
    & $VenvPython -m pip install --upgrade pip
    Write-Host "[2/6] installing requirements (first run takes a few minutes) ..."
    & $VenvPython -m pip install -r requirements.txt
} else {
    Write-Host "[1/6] .venv found"
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[3/6] generated .env from .env.example"
}

$PcConfig = Join-Path $Root "config\powercontext.env"
if (-not (Test-Path $PcConfig)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $PcConfig) | Out-Null
    Write-Host "[4/6] generating PowerContext config ..."
    "y" | & (Join-Path $Root ".venv\Scripts\powercontext.exe") config init --template --output $PcConfig | Out-Null
}

$PcHome = Join-Path $Root "runtime\powercontext"
New-Item -ItemType Directory -Force -Path $PcHome | Out-Null
$env:POWERCONTEXT_HOME = $PcHome

$ready = $false
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:18000/health/ready" -UseBasicParsing -TimeoutSec 2 | Out-Null
    $ready = $true
} catch { }

if (-not $ready) {
    Write-Host "[5/6] starting PowerContext at http://127.0.0.1:18000 ..."
    $pc = Start-Process -FilePath (Join-Path $Root ".venv\Scripts\powercontext.exe") `
        -ArgumentList "server", "run", "--env-file", "config\powercontext.env", "--port", "18000" `
        -WorkingDirectory $Root -PassThru -WindowStyle Hidden
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:18000/health/ready" -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $ready) { throw "PowerContext did not become ready on port 18000" }
    Write-Host "      PowerContext pid $($pc.Id), data $PcHome"
} else {
    Write-Host "[5/6] PowerContext already running on port 18000"
}

# A ready server on 18000 may belong to a different PowerContext home. Refuse to
# silently split memory across two databases.
$ScopeFile = Join-Path $Root "runtime\powercontext.scope"
try {
    $scope = (Invoke-RestMethod -Uri "http://127.0.0.1:18000/v1/scopes/default" -TimeoutSec 5).scope_id
} catch {
    throw "PowerContext is ready but /v1/scopes/default is unavailable"
}
if (Test-Path $ScopeFile) {
    $expected = (Get-Content $ScopeFile -Raw).Trim()
    if ($expected -and $scope -ne $expected) {
        throw "Port 18000 belongs to a different PowerContext scope ($scope, expected $expected). Stop it or use a clean runtime/powercontext.scope."
    }
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $ScopeFile) | Out-Null
    Set-Content -Path $ScopeFile -Value $scope -NoNewline
}
Write-Host "      memory scope $scope"

if (-not $SkipSeed) {
    Write-Host "[6/6] loading demo corpus (idempotent) ..."
    & $VenvPython scripts\seed.py
} else {
    Write-Host "[6/6] seed skipped"
}

$port = if ($env:PAPERDESK_PORT) { $env:PAPERDESK_PORT } else { "8080" }
Write-Host ""
Write-Host "  PaperDesk   ->  http://127.0.0.1:$port"
Write-Host "  PowerContext->  http://127.0.0.1:18000"
Write-Host "  API docs    ->  http://127.0.0.1:$port/api/docs"
Write-Host ""
& $VenvPython backend\run.py
