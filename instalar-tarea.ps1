# Registra el monitor de licitaciones en el Programador de tareas de Windows.
#
# Ejecutar UNA sola vez, con clic derecho > "Ejecutar con PowerShell".
# Si Windows bloquea el script, abrir PowerShell y correr:
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# y luego volver a lanzarlo.
#
# Para desinstalar la tarea despues:
#     Unregister-ScheduledTask -TaskName "Remantico - Monitor de licitaciones" -Confirm:$false

$ErrorActionPreference = "Stop"

$nombre = "Remantico - Monitor de licitaciones"
$carpeta = $PSScriptRoot
$bat = Join-Path $carpeta "ejecutar.bat"

if (-not (Test-Path $bat)) {
    Write-Host "No se encontro ejecutar.bat en $carpeta" -ForegroundColor Red
    exit 1
}

# Si ya existia una version previa de la tarea, se reemplaza.
try {
    Unregister-ScheduledTask -TaskName $nombre -Confirm:$false -ErrorAction Stop
    Write-Host "Tarea anterior eliminada."
} catch {
    # No existia: es lo normal en la primera instalacion.
}

$accion = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $carpeta

# Cuatro revisiones al dia: 8, 13, 18 y 22 horas.
# El portal publica en horario habil, revisar mas seguido no aporta.
$disparadores = @(
    (New-ScheduledTaskTrigger -Daily -At 8:00am),
    (New-ScheduledTaskTrigger -Daily -At 1:00pm),
    (New-ScheduledTaskTrigger -Daily -At 6:00pm),
    (New-ScheduledTaskTrigger -Daily -At 10:00pm)
)

$ajustes = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -MultipleInstances IgnoreNew

# -StartWhenAvailable hace que, si la PC estaba apagada a la hora
# programada, la revision se ejecute en cuanto vuelva a encender.

Register-ScheduledTask `
    -TaskName $nombre `
    -Action $accion `
    -Trigger $disparadores `
    -Settings $ajustes `
    -Description "Revisa el Portal de Contrataciones Abiertas de Chihuahua y reporta licitaciones relevantes para Remantico." | Out-Null

Write-Host ""
Write-Host "Tarea instalada correctamente." -ForegroundColor Green
Write-Host "Nombre:    $nombre"
Write-Host "Horarios:  8:00, 13:00, 18:00 y 22:00 todos los dias"
Write-Host "Carpeta:   $carpeta"
Write-Host ""
Write-Host "Para probarla ahora mismo sin esperar:"
Write-Host "    Start-ScheduledTask -TaskName `"$nombre`"" -ForegroundColor Cyan
Write-Host ""
Write-Host "El reporte queda en: $(Join-Path $carpeta 'reporte.html')"
