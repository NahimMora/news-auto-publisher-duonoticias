[CmdletBinding()]
param(
    [switch]$Disable
)

# Registra (o actualiza) la tarea DuoNoticias-Vigilante: cada hora corre
# `cli.main ops-report --watchdog`, que avisa por correo si el servicio 24/7 dejo
# de latir y manda el reporte de 3 dias aunque el servicio este caido.
# Es independiente de DuoNoticias-24x7 a proposito.

$ErrorActionPreference = "Stop"

$taskName = "DuoNoticias-Vigilante"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if ($env:COMPUTERNAME -ne "FERNANDO") {
    throw "La tarea de produccion solo se registra en FERNANDO (COMPUTERNAME=$env:COMPUTERNAME)."
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Falta $python"
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-m cli.main ops-report --watchdog" `
    -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours 1)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Vigilante de DuoNoticias: aviso por correo si el 24/7 se detiene y reporte de 3 dias" `
    -Force | Out-Null

if ($Disable) {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    Write-Output "Tarea $taskName registrada DESHABILITADA."
} else {
    Write-Output "Tarea $taskName registrada; corre cada hora."
}
