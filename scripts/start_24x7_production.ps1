[CmdletBinding()]
param(
    [switch]$ValidateOnly
)

# Arranque 24/7 de produccion (tarea DuoNoticias-24x7, cada 5 minutos).
# Idempotente: si el supervisor ya corre, run-24-7 toma el lock y esta instancia sale.
# Mismo esquema que C:\LVR\scripts\start_24x7_production.ps1.

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $repoRoot "logs"
$log = Join-Path $logDir "start_24x7.log"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "No existe el entorno virtual esperado: $python"
}
if ($env:COMPUTERNAME -ne "FERNANDO") {
    throw "Produccion solo en FERNANDO (COMPUTERNAME=$env:COMPUTERNAME)."
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 5MB) {
    Move-Item -LiteralPath $log -Destination "$log.1" -Force
}

function Write-StartLog([string]$message) {
    $line = "[{0}] {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $message
    Add-Content -LiteralPath $log -Value $line -Encoding utf8
}

# Perfil operativo explicito. Los secretos y los interruptores por plataforma
# (ENABLE_INSTAGRAM, ENABLE_FACEBOOK, ENABLE_DUO_WEB, DUO_WEB_MODE) viven en .env.
$env:DUO_LIVE_PUBLISH_ENABLED = "true"
$env:DUO_SAFE_MODE_DEFAULT = "false"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

Set-Location -LiteralPath $repoRoot

# PowerShell 5.1 turns native stderr lines into terminating errors under "Stop"
# when merged with 2>&1; python logging writes to stderr, so relax it here.
$ErrorActionPreference = "Continue"
$preflight = & $python -m cli.main preflight 2>&1 | Out-String
$preflightExit = $LASTEXITCODE
if ($preflightExit -ne 0) {
    Write-StartLog "preflight fallo (exit $preflightExit); no se inicia el supervisor."
    Add-Content -LiteralPath $log -Value $preflight -Encoding utf8
    Write-Error "El preflight fallo; no se inicia el pipeline. Ver $log"
    exit 1
}

if ($ValidateOnly) {
    Write-Output $preflight
    Write-Output "Perfil 24/7 valido; no se inicio el supervisor."
    exit 0
}

Write-StartLog "preflight ok; iniciando run-24-7 --live"
& $python -m cli.main run-24-7 --live
$exitCode = $LASTEXITCODE
Write-StartLog "run-24-7 termino (exit $exitCode)"
exit $exitCode
