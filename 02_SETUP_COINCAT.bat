@echo off
setlocal
cd /d "%~dp0"
echo CoinCat v1.05 source preview - Manual Spot and intelligent 24-hour shadow
if exist ".venv\Scripts\python.exe" goto packages
py -3.11 -m venv ".venv"
if errorlevel 1 (
 echo Install Windows Python 3.11 with its py launcher, then retry.
 pause
 exit /b 3
)
:packages
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --require-hashes -r "%~dp0app_requirements.lock"
if errorlevel 1 goto fail
call "%~dp0tools\CREATE_SHORTCUTS.bat"
echo Setup complete. Run 03_VERIFY_COINCAT.bat before starting.
pause
exit /b 0
:fail
echo Dependency installation failed. Existing private data was not changed.
pause
exit /b 5
