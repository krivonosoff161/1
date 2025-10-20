@echo off
chcp 65001 >nul
title OKX Trading Bot - Stop
color 0C
echo =====================================
echo   STOP OKX Trading Bot
echo =====================================
echo.

REM Kill only bot processes (python.exe with run_bot.py)
echo Searching for bot processes...

REM Get all python.exe PIDs running run_bot.py
for /f "tokens=2" %%i in ('wmic process where "name='python.exe' and commandline like '%%run_bot.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    echo Found bot process: PID %%i
    taskkill /PID %%i /F 2>nul
    if !ERRORLEVEL! EQU 0 (
        echo SUCCESS: Stopped PID %%i
    ) else (
        echo WARNING: Could not stop PID %%i
    )
)

REM Fallback: если не нашли специфичные процессы, убиваем все python.exe
wmic process where "name='python.exe' and commandline like '%%run_bot.py%%'" get processid 2>nul | findstr /r "[0-9]" >nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo No bot processes found, checking for any python.exe...
    tasklist /FI "IMAGENAME eq python.exe" | find /I "python.exe" >nul
    if %ERRORLEVEL% EQU 0 (
        echo Found Python processes, stopping all...
        taskkill /IM python.exe /F 2>nul
    ) else (
        echo No Python processes running
    )
)

echo.
echo =====================================
echo Operation completed
echo =====================================
pause
