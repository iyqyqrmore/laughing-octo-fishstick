@echo off
setlocal
cd /d "%~dp0"
py -3.11 -c "import tkinter; assert tkinter.TkVersion >= 8.6"
if errorlevel 1 goto :failed
if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv ".venv"
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -m pip install --require-hashes --only-binary=:all: -r requirements.lock
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" verify_source.py
if errorlevel 1 goto :failed
echo Setup complete. Open 01_START_COINCAT.bat.
pause
exit /b 0
:failed
echo Setup did not complete. Check Python 3.11, Tkinter and the dependency download.
pause
exit /b 1
