@echo off
setlocal
cd /d "%~dp0"
echo =======================================================
echo CoinCat v70.1.1 - ONE-TIME LOCAL SOURCE ENVIRONMENT SETUP
echo No PyInstaller / no EXE compilation / no Coinbase orders
echo =======================================================
if exist ".venv\Scripts\python.exe" goto packages
py -3.11 -m venv ".venv"
if errorlevel 1 (
 if exist "%LOCALAPPDATA%\Python\pythoncore-3.11-64\python.exe" (
  echo Trying Windows Python 3.11 from the verified user installation.
  "%LOCALAPPDATA%\Python\pythoncore-3.11-64\python.exe" -m venv ".venv"
 )
 if not exist ".venv\Scripts\python.exe" (
  echo BLOCKED: Install a normal Python 3.11 Windows interpreter with py launcher.
  pause
  exit /b 3
 )
)
:packages
"%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --require-hashes -r "%~dp0app_requirements.lock"
if errorlevel 1 goto fail
if /I "%~1"=="--cpu-only" goto cpu_ready
REM CUDA PyTorch wheels can be large. Installation occurs ONLY in .venv.
"%~dp0.venv\Scripts\python.exe" -c "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))" >nul 2>&1
if errorlevel 1 (
 echo Installing CUDA PyTorch inside CoinCat v70 .venv. Internet/disk required.
 "%~dp0.venv\Scripts\python.exe" -m pip install --disable-pip-version-check torch --index-url https://download.pytorch.org/whl/cu126
 if errorlevel 1 goto fail
)
set "PYTHONPATH=%~dp0app"
"%~dp0.venv\Scripts\python.exe" -B "%~dp0app\coincat_v60_launcher.py" --verify-cuda-runtime
if errorlevel 1 goto fail
echo PASS: Local v70 environment and CUDA allocation verified.
goto shortcuts
:cpu_ready
echo CPU research and offline verification installed. GPU training is unavailable in this mode.
:shortcuts
call "%~dp004_CREATE_BRANDED_SHORTCUTS_V70.bat"
echo Setup finished. Run 01_START_COINCAT_V70.bat or branded shortcut.
pause
exit /b 0
:fail
echo BLOCKED: Installation or CUDA check failed. No live orders permitted.
pause
exit /b 5
