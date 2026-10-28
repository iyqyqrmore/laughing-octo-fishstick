@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%~dp0app"
set "COINCAT_DATA_DIR=%~dp0private_data"
"%~dp0.venv\Scripts\python.exe" -B "%~dp0app\coincat_data_transfer.py" check --pick-folder
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
