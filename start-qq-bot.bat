@echo off
rem start-qq-bot.bat - start local QQ low-level API (NapCat injects into QQNT, admin required)
rem QQ path is resolved from the registry (UninstallString) so it survives QQ reinstalls/moves.
setlocal DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1

net session >nul 2>&1
if not errorlevel 1 goto elevated

echo [start-qq-bot] requesting administrator privileges...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WindowStyle Minimized"
exit /b 0

:elevated
echo [start-qq-bot] admin OK, starting...
cd /d "%~dp0napcat" || exit /b 1
chcp 65001 >nul

rem ---------- account / optional quick-login password ----------
set "BOT_UIN=1427259367"
if exist "%~dp0account.txt" for /f "usebackq delims=" %%u in ("%~dp0account.txt") do set "BOT_UIN=%%u"
if not defined BOT_UIN set "BOT_UIN=1427259367"
echo [start-qq-bot] account: %BOT_UIN%

rem ---------- locate QQNT ----------
rem 1) registry UninstallString: "D:\...\Uninstall.exe" -> D:\...\QQ.exe
set "UNINST="
set "QQDIR="
set "QQPATH="
for /f "tokens=2*" %%a in ('reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ" /v UninstallString 2^>nul') do set "UNINST=%%~b"
if not defined UNINST goto try_programfiles
for %%a in ("%UNINST%") do set "QQDIR=%%~dpa"
if exist "%QQDIR%QQ.exe" set "QQPATH=%QQDIR%QQ.exe"
if defined QQPATH goto got_qq

:try_programfiles
if exist "%ProgramFiles%\Tencent\QQNT\QQ.exe" set "QQPATH=%ProgramFiles%\Tencent\QQNT\QQ.exe"
if defined QQPATH goto got_qq
if exist "%ProgramFiles(x86)%\Tencent\QQNT\QQ.exe" set "QQPATH=%ProgramFiles(x86)%\Tencent\QQNT\QQ.exe"
if defined QQPATH goto got_qq

echo.
echo [start-qq-bot] ERROR: QQ.exe not found. Nothing was killed.
echo   Registry UninstallString: %UNINST%
echo   Tried: %QQDIR%QQ.exe
echo   Tried: %ProgramFiles%\Tencent\QQNT\QQ.exe
echo.
echo   Fix the QQ install, or edit this script and set QQPATH manually.
pause
exit /b 1

:got_qq
if not exist "%CD%\NapCatWinBootMain.exe" goto missing_napcat
if not exist "%CD%\NapCatWinBootHook.dll" goto missing_napcat
if not exist "%CD%\qqnt.json" goto missing_napcat
echo [start-qq-bot] QQPath=%QQPATH%

rem ---------- restart QQ with injection ----------
taskkill /f /im QQ.exe >nul 2>&1
ping -n 6 127.0.0.1 >nul

set "NAPCAT_PATCH_PACKAGE=%CD%\qqnt.json"
set "NAPCAT_LOAD_PATH=%CD%\loadNapCat.js"
set "NAPCAT_INJECT_PATH=%CD%\NapCatWinBootHook.dll"
set "NAPCAT_LAUNCHER_PATH=%CD%\NapCatWinBootMain.exe"
set "NAPCAT_MAIN_PATH=%CD%\napcat.mjs"

rem Optional quick-login password (created by the deployment script; leave absent to use QR login)
if exist "%~dp0napcat\qq-password.txt" for /f "usebackq delims=" %%p in ("%~dp0napcat\qq-password.txt") do set "NAPCAT_QUICK_PASSWORD=%%p"

del /q "%CD%\cache\qrcode*.png" >nul 2>&1
del /q "%CD%\cache\qrcode*.jpg" >nul 2>&1
echo [start-qq-bot] injecting NapCat into QQNT...
rem Run the launcher in the background: it blocks for the whole QQ lifetime.
rem Keeping it in this console means closing this window terminates QQ.
start "" /b "%CD%\NapCatWinBootMain.exe" "%QQPATH%" "%CD%\NapCatWinBootHook.dll" %BOT_UIN% > "%CD%\logs\bat-stdout.log" 2> "%CD%\logs\bat-stderr.log"
ping -n 4 127.0.0.1 >nul

findstr /c:"Error Code" "%CD%\logs\bat-stderr.log" >nul 2>&1
if not errorlevel 1 (
    echo [start-qq-bot] WARNING: launcher reported an error:
    type "%CD%\logs\bat-stderr.log"
    pause
    exit /b 1
)

echo [start-qq-bot] waiting for NapCat API on 127.0.0.1:3000 ...
echo [start-qq-bot] If QQ asks for QR login, scan it within 3 minutes.
set "NAP_READY="
set "QR_SHOWN="
for /l %%i in (1,1,90) do (
    ping -n 3 127.0.0.1 >nul
    netstat -ano | findstr /r /c:":3000 .*LISTENING" >nul 2>&1 && set "NAP_READY=1"
    if defined NAP_READY goto nap_ready
    if not defined QR_SHOWN if exist "%CD%\cache\qrcode.png" call :show_qr
)
echo [start-qq-bot] WARNING: port 3000 is not listening after 180s.
echo   If the QR expired, close this window and run start-qq-bot.bat again.
echo   Check logs\bat-stdout.log and logs\bat-stderr.log.
goto done

:nap_ready
echo [start-qq-bot] OK: NapCat API is listening on 127.0.0.1:3000.
echo [start-qq-bot] Keep this window open while the bot is in use (closing it can terminate QQ).
goto done

:missing_napcat
echo [start-qq-bot] ERROR: NapCat files missing in %CD%
echo   Need NapCatWinBootMain.exe, NapCatWinBootHook.dll, qqnt.json.
pause
exit /b 1

:done
pause
exit /b 0

:show_qr
set "QRJPG=%CD%\cache\qrcode-login-%RANDOM%.jpg"
copy /y "%CD%\cache\qrcode.png" "%QRJPG%" >nul 2>&1
echo [start-qq-bot] QR login required. Open: %QRJPG%
if exist "%QRJPG%" (
    start "" "%QRJPG%"
) else (
    start "" "%CD%\cache\qrcode.png"
)
set "QR_SHOWN=1"
goto :eof
