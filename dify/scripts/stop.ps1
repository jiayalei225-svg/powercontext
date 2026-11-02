# Stop Moonfall local services started by scripts/start.ps1
$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root "logs\pids.json"
if (-not (Test-Path $PidFile)) {
    Write-Host "No logs\pids.json; nothing to stop."
    exit 0
}
$pids = Get-Content $PidFile -Raw | ConvertFrom-Json
foreach ($name in @("powercontext", "shim")) {
    $id = $pids.$name
    if ($id -and $id -ne 0) {
        try {
            Stop-Process -Id $id -Force -ErrorAction Stop
            Write-Host "Stopped $name (PID $id)"
        } catch {
            Write-Host "$name (PID $id) was not running"
        }
    }
}
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
