@echo off
cd /d "%~dp0"
set PYTHONUTF8=1

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw x_studio_ui.py
) else (
    start "" python x_studio_ui.py
)
