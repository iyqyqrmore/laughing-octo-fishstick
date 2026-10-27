@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run 02_SETUP_COINCAT_V60.bat first.&pause&exit /b 2)
set "PYTHONPATH=%~dp0app"
"%~dp0.venv\Scripts\python.exe" -B "%~dp0app\coincat_v60_launcher.py" --verify-cuda-runtime
if errorlevel 1 (echo FAIL: v60 local CUDA unavailable.&pause&exit /b 5)
echo PASS: v60 LOCAL source-mode CUDA allocation worked; no EXE needed.
pause
