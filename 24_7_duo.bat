@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

title AutoPublicador Duo 24/7

if "%DUO_LOOP_MINUTES%"=="" set DUO_LOOP_MINUTES=60

echo ==========================================
echo   AutoPublicador Duo - Runtime unico 24/7
echo ==========================================
echo.
echo Intervalo: %DUO_LOOP_MINUTES% minutos
echo Publicacion live: bloqueada por defecto
if /I "%DUO_247_LIVE%"=="true" echo Publicacion live solicitada por DUO_247_LIVE=true
if "%DUO_247_LIVE%"=="1" echo Publicacion live solicitada por DUO_247_LIVE=1
if /I "%DUO_247_LIVE%"=="true" echo Modo live: el ciclo espera al proximo bloque 09, 12, 15, 18 o 21.
if "%DUO_247_LIVE%"=="1" echo Modo live: el ciclo espera al proximo bloque 09, 12, 15, 18 o 21.
echo Para detenerlo: Ctrl + C
echo.

set DUO_247_ARGS=run-24-7 --interval-minutes %DUO_LOOP_MINUTES%
if /I "%DUO_247_LIVE%"=="true" set DUO_247_ARGS=%DUO_247_ARGS% --live
if "%DUO_247_LIVE%"=="1" set DUO_247_ARGS=%DUO_247_ARGS% --live

python -m cli.main %DUO_247_ARGS%
