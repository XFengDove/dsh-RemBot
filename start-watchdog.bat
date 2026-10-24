@echo off
rem start-watchdog.bat - start the offline/network watchdog (admin required)
setlocal DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
chcp 65001 >nul

if /I "%~1"=="--elevated" goto elevated
echo [watchdog] requesting administrator privileges...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '--elevated' -Verb RunAs"
exit /b 0

:elevated
set "PY="
for /d %%d in ("%USERPROFILE%\Python*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /d %%d in ("%ProgramFiles%\Python*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY "%%i" -c "import sys" >nul 2>&1 && set "PY=%%i"
if not defined PY (
    echo [watchdog] Python 3 not found.
    pause
    exit /b 1
)

echo [watchdog] Python: %PY%
echo [watchdog] starting watchdog (log: watchdog.log) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PY%' -ArgumentList 'watchdog.py','--config','rem_config.json' -WorkingDirectory '%CD%' -WindowStyle Hidden"
echo [watchdog] started.
pause
