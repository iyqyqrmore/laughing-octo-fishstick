@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Run 02_SETUP_COINCAT.bat first using Windows Python 3.11.
  pause
  exit /b 1
)
echo CoinCat v1.02: offline synthetic paper replay. No account connection.
".venv\Scripts\python.exe" -B VERIFY_SOURCE.py
if errorlevel 1 (
  echo Source verification failed. Replay stopped.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -B tools\PAPER_LIFECYCLE_REPLAY.py --synthetic
set "COINCAT_REPLAY_EXIT=%ERRORLEVEL%"
pause
exit /b %COINCAT_REPLAY_EXIT%
