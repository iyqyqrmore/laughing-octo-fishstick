@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%~dp0app;%~dp0"
set "COINCAT_DATA_DIR=%TEMP%\CoinCat_Verify_Disposable_%RANDOM%%RANDOM%"
echo CoinCat v1.05: SHA256 preview verification plus isolated source tests.
echo [1/3] Checking source hashes...
"%~dp0.venv\Scripts\python.exe" -u -B VERIFY_SOURCE.py
if errorlevel 1 goto fail
echo [2/3] Verifying Python source syntax against the installed Windows interpreter...
set "PYTHONPYCACHEPREFIX=%COINCAT_DATA_DIR%\pycache"
"%~dp0.venv\Scripts\python.exe" -u -B -m compileall -q app offline_tests verification v106 VERIFY_SOURCE.py
if errorlevel 1 goto fail
echo [3/3] Running isolated tests with names, elapsed times and a 30-second heartbeat...
echo Includes the separate v1.06 fee, candle, backtest and GUI recovery tests.
echo Windows tests can take 20 minutes or more. An E or FAIL requires the final error details.
"%~dp0.venv\Scripts\python.exe" -u -B "%~dp0tools\RUN_OFFLINE_TESTS.py"
if errorlevel 1 goto fail
echo PASS: All isolated offline source tests completed.
echo Tests made no exchange calls. Live block defaults ON; deliberate OFF enables REAL manual LIMIT order clicks.
echo Original private ledger untouched by these isolated tests.
pause
exit /b 0
:fail
echo FAIL: Source verification or offline tests failed. No live trading.
pause
exit /b 5
