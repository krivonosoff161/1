@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title OKX Trading Bot - Stop
color 0C
echo =====================================
echo   STOP OKX Trading Bot
echo =====================================
echo.

echo Searching for bot processes...

REM Method 1: Use tasklist to find python.exe processes
set "found=0"
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FO CSV ^| findstr /I "python.exe"') do (
    set "pid=%%i"
    set "pid=!pid:"=!"
    
    REM Check if this process is running run_bot.py
    wmic process where "processid=!pid!" get commandline 2>nul | findstr /I "run_bot.py" >nul
    if !ERRORLEVEL! EQU 0 (
        echo Found bot process: PID !pid!
        taskkill /PID !pid! /F >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo SUCCESS: Stopped PID !pid!
        ) else (
            echo WARNING: Could not stop PID !pid!
        )
        set "found=1"
    )
)

REM Method 2: Fallback - kill all python.exe if no specific processes found
if !found! EQU 0 (
    echo.
    echo No specific bot processes found, checking for any python.exe...
    tasklist /FI "IMAGENAME eq python.exe" 2>nul | find /I "python.exe" >nul
    if !ERRORLEVEL! EQU 0 (
        echo Found Python processes, stopping all...
        taskkill /IM python.exe /F >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo SUCCESS: All Python processes stopped
        ) else (
            echo WARNING: Could not stop some Python processes
        )
    ) else (
        echo No Python processes running
    )
)

echo.
echo =====================================
echo Operation completed
echo =====================================
pause