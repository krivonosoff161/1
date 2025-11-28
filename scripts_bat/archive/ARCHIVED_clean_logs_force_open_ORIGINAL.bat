@echo off
cmd /k "%~f0" %*
exit /b

@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Clean Logs - Force Open
color 0A

echo ====================================
echo   CLEAN LOGS
echo ====================================
echo.

cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Failed to change directory!
    echo Current: %CD%
    echo Script: %~dp0
    echo.
    echo Type EXIT to close
    goto :end
)

echo Current directory: %CD%
echo.

set filefound=0
if exist "logs\futures\*.log" set filefound=1
if exist "logs\futures\*.zip" set filefound=1
if exist "logs\futures\debug\*.csv" set filefound=1
if exist "logs\futures\extracted\*.*" set filefound=1
if exist "logs\futures\temp_extracted\*.*" set filefound=1
if exist "logs\trades_*.csv" set filefound=1
if exist "logs\trades_*.json" set filefound=1

if !filefound! equ 0 (
    echo No files found for archiving!
    echo.
    goto :end
)

if not exist "logs\futures\archived" mkdir "logs\futures\archived"

set datetime=
for /f "tokens=*" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format \"yyyyMMddHHmmss\"" 2^>nul') do set datetime=%%I
if "!datetime!"=="" (
    for /f "tokens=2 delims==" %%I in ('wmic OS Get localdatetime /value 2^>nul') do set datetime=%%I
    set datetime=!datetime:~0,14!
)
if "!datetime!"=="" (
    echo [ERROR] Failed to get date and time!
    echo.
    goto :end
)

set datefolder=logs_!datetime:~0,4!-!datetime:~4,2!-!datetime:~6,2!_!datetime:~8,2!-!datetime:~10,2!-!datetime:~12,2!
set archivefolder=logs\futures\archived\!datefolder!

if not exist "!archivefolder!" mkdir "!archivefolder!"

echo Archive folder: !archivefolder!
echo.

set logcount=0
set zipcount=0
set debugcsvcount=0
set tradescount=0
set jsoncount=0
set extractedcount=0
set tempextractedcount=0

echo Moving LOG files...
for %%f in (logs\futures\*.log) do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 set /a logcount+=1
    )
)

echo Moving ZIP archives...
for %%f in (logs\futures\*.zip) do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 set /a zipcount+=1
    )
)

echo Moving DEBUG CSV files...
if exist "logs\futures\debug" (
    for %%f in (logs\futures\debug\*.csv) do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a debugcsvcount+=1
        )
    )
)

echo Moving TRADE CSV files...
for %%f in ("logs\trades_*.csv") do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 set /a tradescount+=1
    )
)

echo Moving JSON files...
for %%f in ("logs\trades_*.json") do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 set /a jsoncount+=1
    )
)

echo Moving EXTRACTED files...
if exist "logs\futures\extracted" (
    for %%f in (logs\futures\extracted\*.*) do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a extractedcount+=1
        )
    )
    rmdir "logs\futures\extracted" >nul 2>&1
)

echo Moving TEMP_EXTRACTED files...
if exist "logs\futures\temp_extracted" (
    for %%f in (logs\futures\temp_extracted\*.*) do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 set /a tempextractedcount+=1
        )
    )
    rmdir "logs\futures\temp_extracted" >nul 2>&1
)

echo.

echo ====================================
echo   SUMMARY
echo ====================================
echo Moved LOG files: !logcount!
echo Moved ZIP archives: !zipcount!
echo Moved DEBUG CSV files: !debugcsvcount!
echo Moved TRADE CSV files: !tradescount!
echo Moved JSON files: !jsoncount!
echo Moved EXTRACTED files: !extractedcount!
echo Moved TEMP_EXTRACTED files: !tempextractedcount!
echo.

set /a totalmoved=!logcount!+!zipcount!+!debugcsvcount!+!tradescount!+!jsoncount!+!extractedcount!+!tempextractedcount!

if !totalmoved! equ 0 (
    echo [WARNING] No files were moved!
    rmdir "!archivefolder!" >nul 2>&1
) else (
    echo Archive folder: !archivefolder!
    echo Total files moved: !totalmoved!
)

:end
echo.
echo ====================================
echo   CLEAN LOGS COMPLETE
echo ====================================
echo.
echo Window will stay open.
echo Type EXIT to close.

