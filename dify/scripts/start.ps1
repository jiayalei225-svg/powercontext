# Moonfall local services (Windows PowerShell 5.1+)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$DataDir = if ($env:POWERCONTEXT_DATA_DIR) { $env:POWERCONTEXT_DATA_DIR } else { Join-Path $env:LOCALAPPDATA "Moonfall\powercontext" }
$env:POWERCONTEXT_DATA_DIR = $DataDir
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null

function Wait-Http([string]$Url, [int]$Seconds = 120) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

if (-not (Test-Path ".venv")) {
    Write-Host "[1/4] Creating .venv"
    python -m venv .venv
}
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Python venv not found: $Python" }

Write-Host "[2/4] Installing dependencies (first run: 1-3 minutes)"
& $Python -m pip install --upgrade pip --quiet
& $Python -m pip install -r (Join-Path $Root "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed; check network or PyPI mirror" }

Write-Host "[3/4] Starting PowerContext on 8099"
$PcLog = Join-Path $Root "logs\powercontext.log"
$Pc = Start-Process -FilePath $Python -ArgumentList @("scripts\run_powercontext.py", "--host", "0.0.0.0", "--port", "8099") `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $PcLog -RedirectStandardError "$PcLog.err"
if (-not (Wait-Http "http://127.0.0.1:8099/health/ready" 180)) {
    throw "PowerContext failed to start. See logs\powercontext.log.err"
}

Write-Host "[4/4] Starting narrator shim on 8101 (optional offline model)"
$ShimLog = Join-Path $Root "logs\shim.log"
$Shim = Start-Process -FilePath $Python -ArgumentList @("tools\openai_shim.py", "--host", "0.0.0.0", "--port", "8101") `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $ShimLog -RedirectStandardError "$ShimLog.err"
if (-not (Wait-Http "http://127.0.0.1:8101/health" 30)) {
    Write-Host "WARN: narrator shim failed to start; use a real model instead."
}

$pids = [ordered]@{
    powercontext = $Pc.Id
    shim = if ($Shim) { $Shim.Id } else { 0 }
    data_dir = $DataDir
    started_at = (Get-Date).ToString("o")
}
$pids | ConvertTo-Json | Set-Content -Path (Join-Path $Root "logs\pids.json") -Encoding UTF8

Write-Host ""
Write-Host "  PowerContext -> http://127.0.0.1:8099   (PID $($Pc.Id))"
Write-Host "  narrator     -> http://127.0.0.1:8101/v1 (model=moonfall-narrator)"
Write-Host "  data dir     -> $DataDir"
Write-Host ""
Write-Host "Next: import dsl\moonfall-werewolf.chatflow.yml into Dify 1.17.0,"
Write-Host "then set POWERCONTEXT_BASE to http://host.docker.internal:8099 (Docker) or http://127.0.0.1:8099 (native)."
Write-Host "Stop: powershell -ExecutionPolicy Bypass -File scripts\stop.ps1"
