@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "ROOT=%CD%"
if not exist "%ROOT%\.venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT.bat first.&pause&exit /b 2)
set "PYTHONPATH=%ROOT%\app;%ROOT%"
set "COINCAT_DATA_DIR=%ROOT%\private_data"
"%ROOT%\.venv\Scripts\python.exe" -B "%ROOT%\app\coincat_launcher.py" --verify-cuda-runtime
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
