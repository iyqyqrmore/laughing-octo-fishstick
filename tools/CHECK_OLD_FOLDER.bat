@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%CD%\app"
set "COINCAT_DATA_DIR=%CD%\private_data"
"%CD%\.venv\Scripts\python.exe" -B "%CD%\app\coincat_data_transfer.py" check --pick-folder
set "COINCAT_RESULT=%ERRORLEVEL%"
pause
exit /b %COINCAT_RESULT%
