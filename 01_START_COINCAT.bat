@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run 02_SETUP_COINCAT.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m coincat
if errorlevel 1 pause
