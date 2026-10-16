@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AutoPublicador Duo - Loop 24/7

if "%TOP_NOTICIAS%"=="" set TOP_NOTICIAS=10
if "%INTERVALO_MINUTOS%"=="" set INTERVALO_MINUTOS=60
if "%LIVE%"=="" set LIVE=false

echo ==========================================
echo   AutoPublicador Duo - Loop Continuo 24/7
echo ==========================================
echo.
echo   Top noticias: %TOP_NOTICIAS% por corrida
echo   Intervalo:    %INTERVALO_MINUTOS% minutos
if /I "%LIVE%"=="true" (
    echo   MODO:         LIVE (publica en IG+FB)
) else (
    echo   MODO:         DRY-RUN (sin publicar)
)
echo   Para detener: Ctrl+C
echo.

set /a INTERVALO_SEG=%INTERVALO_MINUTOS% * 60

:loop
echo [%date% %time%] Iniciando corrida del pipeline...
echo.

if /I "%LIVE%"=="true" (
    python pipeline_runner.py --live --top %TOP_NOTICIAS%
) else (
    python pipeline_runner.py --top %TOP_NOTICIAS%
)

echo.
echo [%date% %time%] Corrida finalizada. Esperando %INTERVALO_MINUTOS% min...
echo.

timeout /t %INTERVALO_SEG% /nobreak >nul

goto loop
