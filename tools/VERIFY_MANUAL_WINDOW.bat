@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%CD%\app;%CD%"
echo CoinCat v1.05: focused manual-window check. No account connection or real orders.
"%CD%\.venv\Scripts\python.exe" -u -B "%CD%\VERIFY_SOURCE.py"
if errorlevel 1 goto fail
"%CD%\.venv\Scripts\python.exe" -u -B "%CD%\tools\RUN_OFFLINE_TESTS.py" --manual-window
if errorlevel 1 goto fail
echo PASS: Focused manual-window tests completed. This is NOT full source acceptance.
echo Run 03_VERIFY_COINCAT.bat for the full isolated suite before connected testing.
pause
exit /b 0
:fail
echo FAIL: Source integrity or focused window tests failed. Keep live orders blocked.
pause
exit /b 5
