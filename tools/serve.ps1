param(
  [int]$Port = 8000,
  [string]$BindHost = "127.0.0.1",
  [switch]$Background,
  [switch]$Reload
)

# Перезапуск локального сервера преферанса
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $root) { $root = Get-Location }

$log = Join-Path $env:TEMP "pref_server.log"
$err = Join-Path $env:TEMP "pref_server.err"

$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conn) {
  Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 700
  Write-Host "Остановлен процесс на порту $Port"
}

if ($Background) {
  $args = @("-m", "uvicorn", "app.main:app", "--host", $BindHost, "--port", $Port, "--log-level", "warning")
  if ($Reload) { $args += @("--reload", "--reload-dir", "app", "--reload-dir", "web") }
  Start-Process -FilePath "python" -ArgumentList $args `
    -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err
  Start-Sleep -Seconds 4
  try {
    $health = Invoke-WebRequest -Uri "http://${BindHost}:$Port/api/health" -UseBasicParsing -TimeoutSec 8
    Write-Host "Сервер запущен: $($health.Content)  (логи: $log / $err)"
  } catch {
    Write-Host "Не удалось проверить сервер: $($_.Exception.Message)"
    Get-Content $err -Tail 20 -ErrorAction SilentlyContinue
  }
} else {
  Set-Location $root
  python -m uvicorn app.main:app --host $BindHost --port $Port --log-level warning
}
