@echo off
rem clear-context.bat - 只清除对话记忆（保留技能记忆）
setlocal DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
chcp 65001 >nul

echo [clear-context] 清除对话记忆（技能记忆保留）...
python rem_bot.py clear
echo.
echo 完成。技能记忆 memory\skill_memory.md 未被改动。
pause
