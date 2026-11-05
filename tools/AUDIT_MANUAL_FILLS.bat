@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
echo CoinCat v1.04: private November 4 GET-only saved-key audit. No order actions.
"%CD%\.venv\Scripts\python.exe" -u -B "%CD%\tools\AUDIT_MANUAL_FILLS.py"
if errorlevel 1 echo Audit incomplete. Keep the report private. No live order action was attempted.
pause
