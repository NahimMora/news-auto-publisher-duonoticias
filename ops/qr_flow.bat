@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "HOST=%~1"
if "%HOST%"=="" set "HOST=100.71.77.60"

set "PORT=%~2"
if "%PORT%"=="" set "PORT=8008"

set "PHONE=%~3"
if "%PHONE%"=="" set "PHONE=5493875060601"

set "TOKEN=%~4"
if "%TOKEN%"=="" if defined WPP_INTERNAL_TOKEN set "TOKEN=%WPP_INTERNAL_TOKEN%"
if "%TOKEN%"=="" if defined INTERNAL_TOKEN set "TOKEN=%INTERNAL_TOKEN%"
if "%TOKEN%"=="" set /p TOKEN=Ingresa X-Internal-Token: 
if "%TOKEN%"=="" (
  echo [ERROR] Falta token interno.
  echo Uso: ops\qr_flow.bat [HOST] [PORT] [PHONE] [TOKEN]
  exit /b 1
)

set "BASE=http://%HOST%:%PORT%"
set "QR_FILE=qr_%PHONE%.png"

echo [INFO] BASE=%BASE%
echo [INFO] PHONE=%PHONE%
echo.

where curl >nul 2>&1
if errorlevel 1 (
  echo [ERROR] curl no esta disponible en esta maquina.
  exit /b 1
)

where tailscale >nul 2>&1
if errorlevel 1 (
  echo [WARN] tailscale no encontrado. Continuo igual.
) else (
  echo [STEP] tailscale ping %HOST%
  tailscale ping %HOST%
  if errorlevel 1 echo [WARN] tailscale ping fallo. Revisa conexion en la maquina A.
  echo.
)

echo [STEP] Health check...
call :http_get "/health" noauth "health.json"
if not "%HTTP_CODE%"=="200" (
  echo [ERROR] /health devolvio HTTP %HTTP_CODE%
  if exist health.json type health.json
  exit /b 1
)
echo [OK] /health HTTP 200
if exist health.json type health.json
echo.

echo [STEP] Init session...
call :http_post "/session/%PHONE%/init" "init.json"
if not "%HTTP_CODE%"=="200" if not "%HTTP_CODE%"=="201" (
  echo [ERROR] /init devolvio HTTP %HTTP_CODE%
  if exist init.json type init.json
  exit /b 1
)
echo [OK] /init HTTP %HTTP_CODE%
if exist init.json type init.json
echo.

echo [STEP] Descargar QR...
for /f %%i in ('curl -sS -o "%QR_FILE%" -w "%%{http_code}" -H "X-Internal-Token: %TOKEN%" "%BASE%/session/%PHONE%/qr"') do set "HTTP_CODE=%%i"
if not "%HTTP_CODE%"=="200" (
  echo [ERROR] /qr devolvio HTTP %HTTP_CODE%
  if exist "%QR_FILE%" del /q "%QR_FILE%" >nul 2>&1
  exit /b 1
)
for %%A in ("%QR_FILE%") do set "QR_SIZE=%%~zA"
if "%QR_SIZE%"=="" set "QR_SIZE=0"
if "%QR_SIZE%"=="0" (
  echo [ERROR] Se descargo %QR_FILE% vacio.
  exit /b 1
)
echo [OK] QR guardado en %QR_FILE% ^(%QR_SIZE% bytes^)
echo.

echo [STEP] Estado de sesion...
call :http_get "/session/%PHONE%/status" auth "status.json"
if not "%HTTP_CODE%"=="200" (
  echo [ERROR] /status devolvio HTTP %HTTP_CODE%
  if exist status.json type status.json
  exit /b 1
)
echo [OK] /status HTTP 200
if exist status.json type status.json
echo.
echo [DONE] Escanea %QR_FILE% y vuelve a correr este script para confirmar CONNECTED.
exit /b 0

:http_get
set "HTTP_CODE="
if /I "%~2"=="auth" (
  for /f %%i in ('curl -sS -o "%~3" -w "%%{http_code}" -H "X-Internal-Token: %TOKEN%" "%BASE%%~1"') do set "HTTP_CODE=%%i"
) else (
  for /f %%i in ('curl -sS -o "%~3" -w "%%{http_code}" "%BASE%%~1"') do set "HTTP_CODE=%%i"
)
exit /b 0

:http_post
set "HTTP_CODE="
for /f %%i in ('curl -sS -o "%~2" -w "%%{http_code}" -X POST -H "X-Internal-Token: %TOKEN%" "%BASE%%~1"') do set "HTTP_CODE=%%i"
exit /b 0
