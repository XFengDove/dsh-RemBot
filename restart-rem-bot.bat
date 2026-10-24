@echo off
rem restart-rem-bot.bat - stop the running Rem (if any) and start it again
setlocal DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
chcp 65001 >nul

if not exist rem_bot.pid goto :start
set /p BOT_PID=<rem_bot.pid
echo [rem-bot] stopping pid=%BOT_PID% ...
taskkill /PID %BOT_PID% /T /F >nul 2>&1
del /q rem_bot.pid >nul 2>&1
ping -n 3 127.0.0.1 >nul

:start
call "%~dp0start-rem-bot.bat"
