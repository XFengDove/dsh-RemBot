@echo off
rem 一键部署.bat - interactive deployment for the Rem QQ bot
setlocal DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
chcp 65001 >nul
title Rem QQ Bot - Deploy

set "PY="
for /d %%d in ("%USERPROFILE%\Python*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /d %%d in ("%ProgramFiles%\Python*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY "%%i" -c "import sys" >nul 2>&1 && set "PY=%%i"

if not defined PY (
    echo [deploy] ERROR: no working Python 3 found.
    echo          Install Python 3.10+ first.
    pause
    exit /b 1
)

echo [deploy] Python: %PY%
echo.
"%PY%" deploy.py %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo [deploy] finished with exit code %RC%.
pause
exit /b %RC%
