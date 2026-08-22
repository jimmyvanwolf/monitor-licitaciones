@echo off
REM Lanzador del monitor de licitaciones de Remantico.
REM Lo usa el Programador de tareas de Windows. Tambien se puede
REM ejecutar a mano con doble clic para una revision inmediata.

cd /d "%~dp0"

REM Ruta de Python detectada al instalar. Si algun dia mueves o
REM desinstalas Anaconda, cambia esta linea por la ruta nueva.
set "PY=D:\Descargas\Roop\roop-unleashed-main\installer\installer_files\env\python.exe"

if not exist "%PY%" (
    REM Respaldo: usar el python que este en el PATH del sistema.
    set "PY=python"
)

"%PY%" monitor.py
exit /b %errorlevel%
