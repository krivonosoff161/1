@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title TEST Clean Logs
color 0A

echo ====================================
echo   TEST CLEAN LOGS
echo ====================================
echo.
echo Current directory: %CD%
echo Script location: %~dp0
echo.

cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Failed to change directory!
    pause
    exit /b 1
)

echo Changed to: %CD%
echo.

echo Testing date/time methods...
echo.

rem Test 1: PowerShell
echo Method 1: PowerShell...
for /f "tokens=*" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format \"yyyyMMddHHmmss\"" 2^>nul') do set datetime=%%I
if "!datetime!"=="" (
    echo   PowerShell: FAILED
) else (
    echo   PowerShell: SUCCESS - !datetime!
)

rem Test 2: WMIC
echo Method 2: WMIC...
set datetime=
for /f "tokens=2 delims==" %%I in ('wmic OS Get localdatetime /value 2^>nul') do set datetime=%%I
set datetime=!datetime:~0,14!
if "!datetime!"=="" (
    echo   WMIC: FAILED
) else (
    echo   WMIC: SUCCESS - !datetime!
)

echo.
echo Test complete!
echo Press any key to exit...
pause >nul
