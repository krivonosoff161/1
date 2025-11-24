@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Clean Logs - DEBUG MODE
color 0E

echo.
echo ====================================
echo   CLEAN LOGS - DEBUG MODE
echo ====================================
echo.
echo This window will stay open for debugging
echo.
echo Press any key to start...
pause
echo.
echo Starting...
echo.

cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Failed to change directory!
    echo Current: %CD%
    echo Script: %~dp0
    pause
    exit /b 1
)

echo Changed to: %CD%
echo.

rem Test date/time
echo Testing date/time methods...
set datetime=
for /f "tokens=*" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format \"yyyyMMddHHmmss\"" 2^>nul') do set datetime=%%I
if "!datetime!"=="" (
    echo PowerShell failed, trying WMIC...
    for /f "tokens=2 delims==" %%I in ('wmic OS Get localdatetime /value 2^>nul') do set datetime=%%I
    set datetime=!datetime:~0,14!
)
if "!datetime!"=="" (
    echo WMIC failed, using fallback...
    set datetime=%RANDOM%%RANDOM%
)
echo Date/Time: !datetime!
echo.

rem Check for files
echo Checking for files...
set filefound=0
if exist "logs\futures\*.log" (
    echo   Found LOG files
    set filefound=1
)
if exist "logs\futures\*.zip" (
    echo   Found ZIP files
    set filefound=1
)
if exist "logs\futures\debug\*.csv" (
    echo   Found DEBUG CSV files
    set filefound=1
)
if exist "logs\trades_*.csv" (
    echo   Found TRADE CSV files
    set filefound=1
)
echo.

if !filefound! equ 0 (
    echo No files found!
    echo.
    echo Press any key to exit...
    pause
    exit /b 0
)

echo Files found! Would proceed with archiving...
echo.
echo Press any key to exit...
pause

