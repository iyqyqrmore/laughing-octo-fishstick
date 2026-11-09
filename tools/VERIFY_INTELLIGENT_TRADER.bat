@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%CD%\app;%CD%"
echo CoinCat v1.05: focused intelligent forecast, sizing, native fees, lifecycle, privacy and recovery checks.
"%CD%\.venv\Scripts\python.exe" -u -B "%CD%\VERIFY_SOURCE.py"
if errorlevel 1 goto fail
"%CD%\.venv\Scripts\python.exe" -u -B "%CD%\tools\RUN_OFFLINE_TESTS.py" --intelligent
if errorlevel 1 goto fail
echo PASS: Focused synthetic v1.05 checks. No exchange calls or live authority.
echo Run 03_VERIFY_COINCAT.bat for the full isolated suite before connected testing.
pause
exit /b 0
:fail
echo FAIL: Preserve records and keep live orders blocked. Save the final error details.
pause
exit /b 5
