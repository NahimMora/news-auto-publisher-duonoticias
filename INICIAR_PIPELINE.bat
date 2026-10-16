@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AutoPublicador Duo - Pipeline Instagram / Facebook

if "%TOP_NOTICIAS%"=="" set TOP_NOTICIAS=10
if "%INTERVALO_MINUTOS%"=="" set INTERVALO_MINUTOS=60

echo ==========================================
echo   AutoPublicador Duo - Pipeline 24/7
echo   Instagram + Facebook (Meta Graph API)
echo ==========================================
echo.
echo   Fuentes: TN, Infobae, Ambito, El Tribuno,
echo            Aries Online, Elonce Salta,
echo            Nuevo Diario, NA, Paparazzi...
echo.
echo   Top noticias por corrida: %TOP_NOTICIAS%
echo   Intervalo: %INTERVALO_MINUTOS% minutos
echo.
if /I "%LIVE%"=="true" (
    echo   MODO LIVE: PUBLICANDO en Instagram/Facebook
    echo   Para detener: Ctrl+C
    echo.
    python pipeline_runner.py --live --top %TOP_NOTICIAS%
) else (
    echo   MODO DRY-RUN: Sin publicar (preview)
    echo   Para publicar: set LIVE=true y reiniciar
    echo.
    python pipeline_runner.py --top %TOP_NOTICIAS%
)

echo.
echo Pipeline finalizado. Revisa logs/pipeline_runner.log
pause
