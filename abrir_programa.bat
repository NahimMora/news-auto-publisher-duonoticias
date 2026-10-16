@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set PYTHONUTF8=1

if "%DUO_LOOP_MINUTES%"=="" set DUO_LOOP_MINUTES=60
if "%DUO_MAX_POSTS_BLOCK%"=="" set DUO_MAX_POSTS_BLOCK=15
if not "%~1"=="" set DUO_MENU_OPTION=%~1

title AutoPublicador Duo - Panel

:menu
cls
echo =====================================================
echo              AutoPublicador Duo - Panel
echo =====================================================
echo.
echo  Horarios automaticos: 09, 12, 15, 18, 21
echo  Cupo por bloque: 5 videos + 10 posts
echo  Frescura: solo contenido del dia
echo  Intervalo 24/7: %DUO_LOOP_MINUTES% minutos
echo.
echo  1. Doctor / revisar configuracion
echo  2. Ver cola
echo  3. Preview de publicaciones pendientes
echo  4. Ejecutar 1 ciclo seguro
echo  5. Dry run
echo  6. Importar URL de X
echo.
echo  7. Iniciar 24/7 SEGURO, sin publicar
echo  8. Iniciar 24/7 LIVE, publica en Instagram y Facebook
echo  9. Publicar pendientes LIVE ahora, manual
echo.
echo 10. Recolectar analytics
echo 11. Generar reporte diario
echo 12. Ranking de fuentes X
echo 13. Reencolar pendientes para regenerar
echo.
echo  0. Salir
echo.
if defined DUO_MENU_OPTION (
    set option=%DUO_MENU_OPTION%
    set DUO_MENU_OPTION=
    echo Opcion: !option!
) else (
    set /p option=Elegi una opcion: 
)

if "%option%"=="1" goto doctor
if "%option%"=="2" goto queue
if "%option%"=="3" goto preview
if "%option%"=="4" goto safe_once
if "%option%"=="5" goto dry_run
if "%option%"=="6" goto import_x
if "%option%"=="7" goto live_safe_247
if "%option%"=="8" goto live_247
if "%option%"=="9" goto publish_now_live
if "%option%"=="10" goto analytics
if "%option%"=="11" goto report
if "%option%"=="12" goto ranking
if "%option%"=="13" goto requeue
if "%option%"=="0" goto end

echo.
echo Opcion invalida.
pause
goto menu

:doctor
cls
echo Revisando configuracion...
python -m cli.main doctor
pause
goto menu

:queue
cls
echo Cola actual...
python -m cli.main queue --format table --limit 50
pause
goto menu

:preview
cls
echo Preview de publicaciones pendientes, no publica.
python -m cli.main publish-pending --max-posts %DUO_MAX_POSTS_BLOCK%
pause
goto menu

:safe_once
cls
echo Ejecutando 1 ciclo seguro, no publica.
python -m cli.main run-once --safe-mode --max-posts %DUO_MAX_POSTS_BLOCK%
pause
goto menu

:dry_run
cls
echo Ejecutando dry run completo, no publica.
python -m cli.main dry-run --max-posts %DUO_MAX_POSTS_BLOCK%
pause
goto menu

:import_x
cls
echo Importar URL de X
echo.
set /p xurl=Pega la URL y presiona Enter: 
if "%xurl%"=="" (
    echo No ingresaste URL.
    pause
    goto menu
)
python -m cli.main import-x-url --url "%xurl%"
pause
goto menu

:live_safe_247
cls
echo Iniciando 24/7 seguro.
echo No publica en vivo.
echo Para detenerlo: Ctrl + C
echo.
set DUO_LIVE_PUBLISH_ENABLED=false
set DUO_247_LIVE=
call "24_7_duo.bat"
pause
goto menu

:live_247
cls
echo =====================================================
echo  ATENCION: 24/7 LIVE
echo =====================================================
echo.
echo Esto publica automaticamente en Instagram y Facebook.
echo Solo publica dentro de los bloques 09, 12, 15, 18, 21.
echo El ciclo live espera al proximo bloque antes de analizar y publicar.
echo Para detenerlo: Ctrl + C
echo.
set /p confirm=Escribi LIVE para iniciar: 
if /I not "%confirm%"=="LIVE" (
    echo Cancelado.
    pause
    goto menu
)
set DUO_LIVE_PUBLISH_ENABLED=true
set DUO_247_LIVE=true
call "24_7_duo.bat"
pause
goto menu

:publish_now_live
cls
echo =====================================================
echo  ATENCION: PUBLICACION LIVE MANUAL
echo =====================================================
echo.
echo Esto publica ahora mismo hasta %DUO_MAX_POSTS_BLOCK% contenidos vencidos.
echo Esta opcion no espera al proximo bloque horario.
echo Noticias: politica, policiales o espectaculos del dia.
echo Videos: no se filtran por tema; si por fecha y calidad minima.
echo.
set /p confirm=Escribi PUBLICAR para continuar: 
if /I not "%confirm%"=="PUBLICAR" (
    echo Cancelado.
    pause
    goto menu
)
set DUO_LIVE_PUBLISH_ENABLED=true
python -m cli.main publish-pending --live --max-posts %DUO_MAX_POSTS_BLOCK%
pause
goto menu

:analytics
cls
echo Recolectando analytics...
python -m cli.main analytics-collect
pause
goto menu

:report
cls
echo Generando reporte diario...
python -m cli.main growth-report
pause
goto menu

:ranking
cls
echo Mostrando ranking de fuentes X...
python -m cli.main source-ranking
pause
goto menu

:requeue
cls
echo Reencolar pendientes para regenerar caption y media.
echo No afecta contenidos ya publicados.
echo.
set /p confirm=Escribi REGENERAR para continuar: 
if /I not "%confirm%"=="REGENERAR" (
    echo Cancelado.
    pause
    goto menu
)
python -m cli.main requeue-pending
pause
goto menu

:end
endlocal
exit /b 0
