param(
    [string]$TaskName = "AutoPublicadorDuo24x7",
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath = Join-Path $Root "autorun_24_7.bat"

if (-not (Test-Path -LiteralPath $BatPath)) {
    throw "No se encontro $BatPath"
}

$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatPath`"" `
    -WorkingDirectory $Root

$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -RestartCount 999 `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "AutoPublicador Duo 24/7 autorun live" `
        -Force | Out-Null
} catch {
    Write-Error "No se pudo registrar la tarea. Ejecuta este script desde tu usuario real o desde PowerShell como administrador. Detalle: $($_.Exception.Message)"
    throw
}

Write-Host "Tarea registrada: $TaskName"
Write-Host "Script: $BatPath"
Write-Host "Logs: $(Join-Path $Root 'logs')"

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Tarea iniciada."
}
