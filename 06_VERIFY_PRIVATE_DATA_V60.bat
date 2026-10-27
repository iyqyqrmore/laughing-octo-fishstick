@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT_V60.bat first.&pause&exit /b 2)
set "PYTHONPATH=%~dp0app"
set "COINCAT_DATA_DIR=%APPDATA%\CoinCatV60"
echo This only READS the current V60 ledger and verifies the marker and SQLite quick_check.
"%~dp0.venv\Scripts\python.exe" -B "%~dp0app\coincat_state_v50.py" verify
if errorlevel 1 (echo V60 state NOT VERIFIED; preserve originals.&pause&exit /b 5)
echo PASS: V60 private data existence and SQLite quick-check verified locally.
echo Coinbase-side fills, FIFO tax basis and live approval NOT VERIFIED.
pause
