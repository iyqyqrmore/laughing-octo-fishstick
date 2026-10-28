@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "ROOT=%CD%"
if not exist "%ROOT%\.venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%ROOT%\app;%ROOT%"
set "COINCAT_DATA_DIR=%ROOT%\private_data"
echo ===========================================================
echo COINCAT VERIFICATION: FIFO & LEDGER
echo No live orders, no financial ledger mutation.
echo ===========================================================
"%ROOT%\.venv\Scripts\python.exe" -B "%ROOT%\verification\run_verification.py" fifo
set "RESULT=%ERRORLEVEL%"
echo FINAL GO-LIVE VERDICT: NOT APPROVED - all order POST blocked.
if not "%RESULT%"=="0" echo Offline/verification test failed; review verification_reports.
pause
exit /b %RESULT%
