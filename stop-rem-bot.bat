@echo off
rem stop-rem-bot.bat - 停止 QQ「雷姆」聊天机器人
setlocal DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
chcp 65001 >nul

if not exist rem_bot.pid (
    echo [rem-bot] 没有找到 rem_bot.pid，机器人可能未在运行。
    pause
    exit /b 0
)

set /p BOT_PID=<rem_bot.pid
echo [rem-bot] 停止进程 PID=%BOT_PID% ...
taskkill /PID %BOT_PID% /T /F >nul 2>&1
del /q rem_bot.pid >nul 2>&1
echo [rem-bot] 已停止。
pause
