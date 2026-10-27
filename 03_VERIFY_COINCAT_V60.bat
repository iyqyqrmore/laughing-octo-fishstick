@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT_V60.bat first.&pause&exit /b 2)
set "PYTHONPATH=%~dp0app;%~dp0"
set "COINCAT_DATA_DIR=%TEMP%\CoinCatV70_Verify_Disposable_%RANDOM%%RANDOM%"
echo CoinCat v70: SHA256 release verification plus isolated source tests.
"%~dp0.venv\Scripts\python.exe" -B VERIFY_SOURCE_V60.py
if errorlevel 1 goto fail
echo Verifying Python source syntax against the installed Windows interpreter...
set "PYTHONPYCACHEPREFIX=%COINCAT_DATA_DIR%\pycache"
"%~dp0.venv\Scripts\python.exe" -m compileall -q app offline_tests verification VERIFY_SOURCE_V60.py
if errorlevel 1 goto fail
"%~dp0.venv\Scripts\python.exe" -B -m unittest discover -s offline_tests -q
if errorlevel 1 goto fail
echo PASS: All isolated offline source tests completed.
echo Live order POST remains blocked. Original private ledger untouched.
pause
exit /b 0
:fail
echo FAIL: Source verification or offline tests failed. No live trading.
pause
exit /b 5
