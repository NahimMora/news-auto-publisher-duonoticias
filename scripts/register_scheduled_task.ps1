[CmdletBinding()]
param(
    [switch]$Disable
)

# Registra (o actualiza) la tarea DuoNoticias-24x7: cada 5 minutos ejecuta
# scripts\start_24x7_production.ps1, que valida con preflight y arranca el
# supervisor solo si no hay otro corriendo (lock en data\runtime).
# Mismo esquema que LaVozRiojana-24x7. No pisa tareas de otros proyectos.

$ErrorActionPreference = "Stop"

$taskName = "DuoNoticias-24x7"
$repoRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $repoRoot "scripts\start_24x7_production.ps1"

if ($env:COMPUTERNAME -ne "FERNANDO") {
    throw "La tarea de produccion solo se registra en FERNANDO (COMPUTERNAME=$env:COMPUTERNAME)."
}
if (-not (Test-Path -LiteralPath $startScript -PathType Leaf)) {
    throw "Falta $startScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`"" `
    -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "AutoPublicador DuoNoticias 24/7 (pipeline cli.main run-24-7 --live)" `
    -Force | Out-Null

if ($Disable) {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    Write-Output "Tarea $taskName registrada DESHABILITADA. Habilitar con: Enable-ScheduledTask -TaskName $taskName"
} else {
    Write-Output "Tarea $taskName registrada; primera ejecucion en 1 minuto y luego cada 5."
}
Write-Output "Verificar: Get-ScheduledTaskInfo -TaskName $taskName"
Write-Output "Salud:     .venv\Scripts\python.exe -m cli.main autorun-health"
