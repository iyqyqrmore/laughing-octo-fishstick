@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "ROOT=%CD%"
if not exist "%ROOT%\.venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%ROOT%\app;%ROOT%"
set "COINCAT_DATA_DIR=%ROOT%\private_data"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\tools\CREATE_SHORTCUTS.ps1"
set "RESULT=%ERRORLEVEL%"
exit /b %RESULT%
