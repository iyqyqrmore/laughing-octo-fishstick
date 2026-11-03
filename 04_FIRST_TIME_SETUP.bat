@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "COINCAT_DATA_DIR=%~dp0private_data"
set "PYTHONPATH=%~dp0app;%~dp0"
"%~dp0.venv\Scripts\python.exe" -B "%~dp0app\coincat_v80_first_run.py" --new
if errorlevel 1 (echo Setup cancelled or blocked. Existing data was not overwritten.&pause&exit /b 2)
echo New v1.01 preview data and initial independent backup verified. Start CoinCat and import your existing authorized key JSON locally.
pause
exit /b 0
