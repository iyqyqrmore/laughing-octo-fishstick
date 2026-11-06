@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%CD%\app;%CD%"
echo CoinCat v1.04: focused opportunity shadow policy, lifecycle, recovery and adverse scenarios.
"%CD%\.venv\Scripts\python.exe" -u -B "%CD%\VERIFY_SOURCE.py"
if errorlevel 1 goto fail
"%CD%\.venv\Scripts\python.exe" -u -B "%CD%\tools\RUN_OFFLINE_TESTS.py" --opportunity
if errorlevel 1 goto fail
echo PASS: Focused opportunity shadow checks completed. No exchange calls or live authority.
echo Run 03_VERIFY_COINCAT.bat for full isolated verification before connected testing.
pause
exit /b 0
:fail
echo FAIL: Source integrity or opportunity checks failed. Preserve records and keep live orders blocked.
pause
exit /b 5
