@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Clean Logs - Keep Open
color 0A

echo.
echo ====================================
echo   CLEAN LOGS
echo ====================================
echo.
echo Press any key to START...
pause >nul
echo.

cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Failed to change directory!
    echo Current: %CD%
    echo Script: %~dp0
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo Current directory: %CD%
echo.
echo Press any key to continue...
pause >nul
echo.

if not exist "logs\futures\archived" (
    echo Creating archive folder...
    mkdir "logs\futures\archived"
    if errorlevel 1 (
        echo [ERROR] Failed to create folder!
        pause >nul
        exit /b 1
    )
)

echo Getting date and time...
for /f "tokens=*" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format \"yyyyMMddHHmmss\"" 2^>nul') do set datetime=%%I
if "!datetime!"=="" (
    echo PowerShell failed, trying WMIC...
    for /f "tokens=2 delims==" %%I in ('wmic OS Get localdatetime /value 2^>nul') do set datetime=%%I
    set datetime=!datetime:~0,14!
)
if "!datetime!"=="" (
    echo [ERROR] Failed to get date!
    pause >nul
    exit /b 1
)

echo Date/Time: !datetime!
set datefolder=logs_!datetime:~0,4!-!datetime:~4,2!-!datetime:~6,2!_!datetime:~8,2!-!datetime:~10,2!-!datetime:~12,2!
set archivefolder=logs\futures\archived\!datefolder!

if not exist "!archivefolder!" mkdir "!archivefolder!"
echo Archive folder: !archivefolder!
echo.
echo Press any key to continue...
pause >nul
echo.

set logcount=0
set zipcount=0
set debugcsvcount=0
set tradescount=0
set jsoncount=0
set extractedcount=0
set tempextractedcount=0

echo Moving LOG files...
if exist "logs\futures\*.log" (
    for %%f in (logs\futures\*.log) do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a logcount+=1
        )
    )
)
echo LOG: !logcount!
echo.

echo Moving ZIP files...
if exist "logs\futures\*.zip" (
    for %%f in (logs\futures\*.zip) do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a zipcount+=1
        )
    )
)
echo ZIP: !zipcount!
echo.

echo Moving DEBUG CSV files...
if exist "logs\futures\debug\*.csv" (
    for %%f in (logs\futures\debug\*.csv) do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a debugcsvcount+=1
        )
    )
)
echo DEBUG CSV: !debugcsvcount!
echo.

echo Moving TRADE CSV files...
if exist "logs\trades_*.csv" (
    for %%f in ("logs\trades_*.csv") do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a tradescount+=1
        )
    )
)
echo TRADE CSV: !tradescount!
echo.

echo Moving JSON files...
if exist "logs\trades_*.json" (
    for %%f in ("logs\trades_*.json") do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a jsoncount+=1
        )
    )
)
echo JSON: !jsoncount!
echo.

echo Moving EXTRACTED files...
if exist "logs\futures\extracted\*.*" (
    for %%f in (logs\futures\extracted\*.*) do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a extractedcount+=1
        )
    )
    rmdir "logs\futures\extracted" >nul 2>&1
)
echo EXTRACTED: !extractedcount!
echo.

echo Moving TEMP_EXTRACTED files...
if exist "logs\futures\temp_extracted\*.*" (
    for %%f in (logs\futures\temp_extracted\*.*) do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a tempextractedcount+=1
        )
    )
    rmdir "logs\futures\temp_extracted" >nul 2>&1
)
echo TEMP_EXTRACTED: !tempextractedcount!
echo.

set /a totalmoved=!logcount!+!zipcount!+!debugcsvcount!+!tradescount!+!jsoncount!+!extractedcount!+!tempextractedcount!

echo.
echo ====================================
echo   SUMMARY
echo ====================================
echo Total files moved: !totalmoved!
echo Archive folder: !archivefolder!
echo.
echo Window will stay open.
echo Type EXIT to close.

