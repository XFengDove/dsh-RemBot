@echo off
rem start-rem-bot.bat - start the Rem QQ bot in background
rem Finds a working Python 3 automatically, removes stale pid files, then starts rem_bot.py.
setlocal DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
chcp 65001 >nul

rem ---------- stale pid check ----------
if not exist rem_bot.pid goto find_python
set /p BOT_PID=<rem_bot.pid
powershell -NoProfile -Command "if (Get-Process -Id %BOT_PID% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if not errorlevel 1 goto already_running
echo [rem-bot] stale pid file ^(%BOT_PID%^), removing.
del /q rem_bot.pid >nul 2>&1
goto find_python

:already_running
echo [rem-bot] already running, pid=%BOT_PID%
echo          To restart, run stop-rem-bot.bat first.
pause
exit /b 0

rem ---------- locate a working Python 3 ----------
:find_python
set "PY="
for /d %%d in ("%USERPROFILE%\Python*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /d %%d in ("%ProgramFiles%\Python*") do if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY "%%i" -c "import sys" >nul 2>&1 && set "PY=%%i"
if not defined PY goto no_python

echo [rem-bot] Python: %PY%
echo [rem-bot] starting Rem in background (log: rem_bot.log) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PY%' -ArgumentList 'rem_bot.py','run' -WorkingDirectory '%CD%' -WindowStyle Hidden -RedirectStandardOutput '%CD%\rem_bot_console.out.log' -RedirectStandardError '%CD%\rem_bot_console.err.log'"

for /l %%i in (1,1,10) do (
    if exist rem_bot.pid goto got_pid
    ping -n 2 127.0.0.1 >nul
)
goto no_pid

:got_pid
set /p NEWPID=<rem_bot.pid
powershell -NoProfile -Command "if (Get-Process -Id %NEWPID% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 goto died
echo [rem-bot] started, pid=%NEWPID%
goto check_port

:died
echo [rem-bot] WARNING: process %NEWPID% exited right after start.
echo          Check rem_bot_console.err.log
goto check_port

:no_pid
echo [rem-bot] WARNING: pid file was not created; check rem_bot_console.err.log

:check_port
netstat -ano | findstr ":5700" >nul 2>&1 && echo [rem-bot] listening on 127.0.0.1:5700
echo [rem-bot] self-test: "%PY%" rem_bot.py selftest
pause
exit /b 0

:no_python
echo [rem-bot] ERROR: no working Python 3 found.
echo          Install Python 3.10+ or edit this script and set PY manually.
pause
exit /b 1
