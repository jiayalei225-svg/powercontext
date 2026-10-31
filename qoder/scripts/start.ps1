# PaperDesk 启动脚本（Windows / PowerShell）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\start.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "[1/4] 创建虚拟环境 .venv ..."
    python -m venv .venv
    & $Python -m pip install --upgrade pip
    Write-Host "[2/4] 安装依赖（首次约 3-5 分钟）..."
    & $Python -m pip install -r requirements.txt
} else {
    Write-Host "[1/4] 已存在 .venv，跳过安装"
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[3/4] 已从 .env.example 生成 .env"
}

$envFile = Join-Path $Root "config\powercontext.env"
if (-not (Test-Path $envFile)) {
    Write-Host "生成 PowerContext 配置 ..."
    "y" | & (Join-Path $Root ".venv\Scripts\powercontext.exe") config init --template --output $envFile | Out-Null
}

Write-Host "[4/4] 启动 PowerContext（记忆服务）..."
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
}
$pc = Start-Process -FilePath (Join-Path $Root ".venv\Scripts\powercontext.exe") `
    -ArgumentList "server", "run" -PassThru -WindowStyle Hidden

for ($i = 0; $i -lt 60; $i++) {
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:8000/health/ready" -UseBasicParsing -TimeoutSec 2 | Out-Null
        break
    } catch { Start-Sleep -Seconds 1 }
}

$port = if ($env:PAPERDESK_PORT) { $env:PAPERDESK_PORT } else { "8080" }
Write-Host ""
Write-Host "  PaperDesk  ->  http://127.0.0.1:$port"
Write-Host "  PowerContext->  http://127.0.0.1:8000  (PID $($pc.Id))"
Write-Host "  首次使用请另开窗口执行：.\.venv\Scripts\python.exe scripts\seed.py"
Write-Host ""

& $Python backend\run.py
