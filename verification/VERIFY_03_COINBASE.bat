@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "ROOT=%CD%"
if not exist "%ROOT%\.venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%ROOT%\app;%ROOT%"
set "COINCAT_DATA_DIR=%ROOT%\private_data"
echo ===========================================================
echo COINCAT VERIFICATION: OPT-IN COINBASE HISTORY GET
echo No live orders, no financial ledger mutation.
echo ===========================================================
echo Optional: THIS ONE SCRIPT uses existing Coinbase credentials for GET ONLY.
echo It never creates, cancels, or transfers an order or money.
set "ACK="
set /p "ACK=Type READONLY GET to authorize bounded authenticated order/fill history: "
if /I not "%ACK%"=="READONLY GET" (echo Cancelled. No Coinbase request.&pause&exit /b 2)
"%ROOT%\.venv\Scripts\python.exe" -B "%ROOT%\verification\run_verification.py" coinbase --authorize-readonly-network
set "RESULT=%ERRORLEVEL%"
echo FINAL GO-LIVE VERDICT: NOT APPROVED - all order POST blocked.
if not "%RESULT%"=="0" echo Offline/verification test failed; review verification_reports.
pause
exit /b %RESULT%
