@echo off
setlocal
call "%~dp0..\02_SETUP_COINCAT.bat" --cuda
exit /b %ERRORLEVEL%
