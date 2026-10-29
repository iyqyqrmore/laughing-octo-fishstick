@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "COINCAT_DATA_DIR=%~dp0private_data"
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app\coincat_start.py"
exit /b 0
