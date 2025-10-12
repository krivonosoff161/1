@echo off
chcp 65001 >nul
title OKX Trading Bot - Stop
color 0C
echo =====================================
echo   STOP OKX Trading Bot
echo =====================================
echo.

REM Simple and reliable way - kill all python.exe
echo Searching for Python processes...

tasklist /FI "IMAGENAME eq python.exe" | find /I "python.exe" >nul

if %ERRORLEVEL% EQU 0 (
    echo Found running Python processes
    echo Stopping all Python processes...
    taskkill /IM python.exe /F 2>nul
    
    if %ERRORLEVEL% EQU 0 (
        echo All Python processes stopped
    ) else (
        echo Could not stop some processes
        echo Administrator rights may be required
    )
) else (
    echo No Python processes found
    echo Bot is already stopped or not running
)

echo.
echo =====================================
echo Operation completed
echo =====================================
pause
