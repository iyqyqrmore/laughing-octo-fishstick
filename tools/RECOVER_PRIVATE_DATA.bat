@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%CD%\app"
set "COINCAT_DATA_DIR=%CD%\private_data"
echo OPTIONAL RECOVERY ONLY. This copies an old COMPLETE dataset, including its encrypted credentials.
echo For a new key and fresh data use 04_FIRST_TIME_SETUP.bat instead. Existing data will not be overwritten.
"%CD%\.venv\Scripts\python.exe" -B "%CD%\app\coincat_data_transfer.py" import
set "COINCAT_RESULT=%ERRORLEVEL%"
pause
exit /b %COINCAT_RESULT%
