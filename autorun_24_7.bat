@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title AutoPublicador Duo - Autorun 24/7

if "%DUO_LOOP_MINUTES%"=="" set "DUO_LOOP_MINUTES=60"
if "%DUO_MAX_POSTS_BLOCK%"=="" set "DUO_MAX_POSTS_BLOCK=15"

set "DUO_LIVE_PUBLISH_ENABLED=true"

if not exist "logs" mkdir "logs"

echo ==================================================>> "logs\autorun_24_7_supervisor.log"
echo [%date% %time%] AutoPublicador Duo autorun start>> "logs\autorun_24_7_supervisor.log"
echo Root: %cd%>> "logs\autorun_24_7_supervisor.log"
echo Loop minutes: %DUO_LOOP_MINUTES%>> "logs\autorun_24_7_supervisor.log"
echo Max posts block: %DUO_MAX_POSTS_BLOCK%>> "logs\autorun_24_7_supervisor.log"

python -m cli.main autorun-health >> "logs\autorun_24_7_supervisor.log" 2>&1
python -m cli.main run-24-7 --live --interval-minutes %DUO_LOOP_MINUTES% --max-posts %DUO_MAX_POSTS_BLOCK% >> "logs\autorun_24_7_console.log" 2>&1

set "EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] AutoPublicador Duo autorun exit %EXIT_CODE%>> "logs\autorun_24_7_supervisor.log"
exit /b %EXIT_CODE%
