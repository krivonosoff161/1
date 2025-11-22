@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Clean Logs
color 0A

cd /d "%~dp0"
if errorlevel 1 (
    echo.
    echo ERROR: Failed to change directory
    echo Current directory: %CD%
    echo.
    echo Press any key to exit...
    pause
    exit /b 1
)

echo ====================================
echo   CLEAN LOGS
echo ====================================
echo.
echo WARNING: Close all programs that may use log or CSV files!
echo.
echo Press any key to continue...
pause
echo.

set filefound=0
if exist "logs\futures\*.log" set filefound=1
if exist "logs\futures\*.zip" set filefound=1
if exist "logs\futures\debug\*.csv" set filefound=1
if exist "logs\trades_*.csv" set filefound=1
if exist "logs\trades_*.json" set filefound=1

if !filefound! equ 0 (
    echo.
    echo No files found for archiving!
    echo.
    echo Press any key to exit...
    pause
    exit /b 0
)

if not exist "logs\futures\archived" mkdir "logs\futures\archived"

set datetime=
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set datetime=%%I
if "!datetime!"=="" (
    echo ERROR: Failed to get date and time!
    echo Press any key to exit...
    pause
    exit /b 1
)
set datefolder=logs_!datetime:~0,4!-!datetime:~4,2!-!datetime:~6,2!_!datetime:~8,2!-!datetime:~10,2!-!datetime:~12,2!
set archivefolder=logs\futures\archived\!datefolder!

if not exist "!archivefolder!" mkdir "!archivefolder!"

echo Created archive folder: !archivefolder!
echo.

set logcount=0
set failedcount=0
set zipcount=0
set failedzip=0
set debugcsvcount=0
set faileddebugcsv=0
set tradescount=0
set failedtrades=0
set jsoncount=0
set failedjson=0
set csv_processed=0
set json_processed=0

echo Moving log files...
for %%f in (logs\futures\*.log) do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a logcount+=1
        ) else (
            set /a failedcount+=1
        )
    )
)

echo Moving ZIP archives...
for %%f in (logs\futures\*.zip) do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a zipcount+=1
        ) else (
            set /a failedzip+=1
        )
    )
)

echo Moving DEBUG CSV files...
if exist "logs\futures\debug" (
    for %%f in (logs\futures\debug\*.csv) do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 (
                set /a debugcsvcount+=1
            ) else (
                set /a faileddebugcsv+=1
            )
        )
    )
)

echo Moving CSV trade files...
for %%f in ("logs\trades_*.csv") do (
    if exist "%%f" (
        set /a csv_processed+=1
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a tradescount+=1
        ) else (
            set /a failedtrades+=1
        )
    )
)

echo Moving JSON trade files...
for %%f in ("logs\trades_*.json") do (
    if exist "%%f" (
        set /a json_processed+=1
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a jsoncount+=1
        ) else (
            set /a failedjson+=1
        )
    )
)

echo.
echo ====================================
echo SUMMARY
echo ====================================
echo Moved LOG files: !logcount!
echo Moved ZIP archives: !zipcount!
echo Moved DEBUG CSV files: !debugcsvcount!
echo Moved TRADE CSV files: !tradescount!
echo Moved JSON files: !jsoncount!
echo.
echo Failed to move: !failedcount! LOG, !failedzip! ZIP, !faileddebugcsv! DEBUG_CSV, !failedtrades! TRADE_CSV, !failedjson! JSON
echo.

set totalmoved=0
set /a totalmoved=!logcount!+!zipcount!+!debugcsvcount!+!tradescount!+!jsoncount!

if !totalmoved! equ 0 (
    echo WARNING: No files were moved!
    echo Removing empty archive folder...
    rmdir "!archivefolder!" >nul 2>&1
    echo Empty folder removed.
) else (
    echo Archive folder: !archivefolder!
    echo Total files moved: !totalmoved!
)

echo.
echo Press any key to exit...
pause
