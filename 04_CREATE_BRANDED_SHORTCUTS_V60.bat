@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\CREATE_SHORTCUTS_V60.ps1"
if errorlevel 1 echo Unable to create Explorer shortcuts. Ordinary BAT launchers still work.
exit /b %errorlevel%
