@echo off
REM DEBUG mode only. For no-console GUI use the CoinCat v60 - START shortcut.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo CoinCat v60 local environment missing. Run 02_SETUP_COINCAT_V60.bat first.
 pause
 exit /b 2
)
set "PYTHONPATH=%~dp0app"
set "COINCAT_DATA_DIR=%APPDATA%\CoinCatV60"
"%~dp0.venv\Scripts\python.exe" -B "%~dp0app\coincat_v60_launcher.py"
if errorlevel 1 (
 echo CoinCat v60 stopped/failed. This release cannot submit live Coinbase orders.
 pause
)
endlocal
