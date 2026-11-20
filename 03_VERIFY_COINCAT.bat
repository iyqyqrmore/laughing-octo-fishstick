@echo off
setlocal
cd /d "%~dp0"
py -3.11 verify_source.py
if errorlevel 1 (
    pause
    exit /b 1
)
pause
