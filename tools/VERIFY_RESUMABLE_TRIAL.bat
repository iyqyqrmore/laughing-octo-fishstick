@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
echo CoinCat v1.04: focused clock, recovery, replay, audit, privacy and tray checks.
"%CD%\.venv\Scripts\python.exe" -u -B "%CD%\VERIFY_SOURCE.py"
if errorlevel 1 goto fail
"%CD%\.venv\Scripts\python.exe" -u -B "%CD%\tools\RUN_OFFLINE_TESTS.py" --trial
if errorlevel 1 goto fail
echo PASS: Focused offline trial checks. Run 03_VERIFY_COINCAT.bat for full source acceptance.
pause
exit /b 0
:fail
echo FAIL: Keep shadow trial paused and live orders blocked. Preserve the final traceback.
pause
exit /b 5
