@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
 echo CoinCat v70.1.1 local Python environment missing. Run 02_SETUP_COINCAT_V70.bat first.
 pause
 exit /b 2
)
REM Normal GUI launch uses pythonw: no persistent black console window.
REM Errors are summarized in private %APPDATA%\CoinCatV70\logs\startup_status.log
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app\coincat_v601_silent.py"
exit /b 0
