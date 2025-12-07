@echo off
setlocal enabledelayedexpansion
chcp 65001
title Clean Logs
color 0A

echo ====================================
echo   CLEAN LOGS
echo ====================================
echo.
echo Script started at %TIME%
echo.

cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Failed to change directory!
    echo Current: %CD%
    echo Script: %~dp0
    echo.
    echo Press any key to exit...
    pause
    exit /b 1
)

echo Current directory: %CD%
echo Script directory: %~dp0
echo.

set filefound=0
if exist "logs\futures\*.log" set filefound=1
if exist "logs\futures\*.zip" set filefound=1
if exist "logs\futures\debug\*.csv" set filefound=1
if exist "logs\futures\structured\*.json" set filefound=1
if exist "logs\futures\extracted" set filefound=1
if exist "logs\futures\temp_extracted" set filefound=1
if exist "logs\trades_*.csv" set filefound=1
if exist "logs\trades_*.json" set filefound=1

echo File found flag: !filefound!
echo.

if !filefound! equ 0 (
    echo No files found for archiving!
    echo.
    echo Press any key to exit...
    pause
    exit /b 0
)

if not exist "logs\futures\archived" (
    echo Creating archive folder...
    mkdir "logs\futures\archived"
    if errorlevel 1 (
        echo [ERROR] Failed to create archive folder!
        echo.
        echo Press any key to exit...
        pause
        exit /b 1
    )
)

echo Getting date and time...
set datetime=
for /f "tokens=*" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format \"yyyyMMddHHmmss\"" 2^>nul') do set datetime=%%I
if "!datetime!"=="" (
    echo PowerShell failed, trying WMIC...
    for /f "tokens=2 delims==" %%I in ('wmic OS Get localdatetime /value 2^>nul') do (
        set datetime=%%I
    )
    if not "!datetime!"=="" (
        set datetime=!datetime:~0,14!
    )
)
if "!datetime!"=="" (
    echo [ERROR] Failed to get date and time!
    echo.
    echo Press any key to exit...
    pause
    exit /b 1
)

echo Date/Time: !datetime!
set datefolder=logs_!datetime:~0,4!-!datetime:~4,2!-!datetime:~6,2!_!datetime:~8,2!-!datetime:~10,2!-!datetime:~12,2!
set archivefolder=logs\futures\archived\!datefolder!

if not exist "!archivefolder!" (
    mkdir "!archivefolder!"
    if errorlevel 1 (
        echo [ERROR] Failed to create archive folder: !archivefolder!
        echo.
        echo Press any key to exit...
        pause
        exit /b 1
    )
)

echo Archive folder: !archivefolder!
echo.

set logcount=0
set failedcount=0
set zipcount=0
set failedzip=0
set debugcsvcount=0
set faileddebugcsv=0
set tradescount=0
set failedtrades=0
set orderscount=0
set failedorders=0
set positionsopencount=0
set failedpositionsopen=0
set signalscount=0
set failedsignals=0
set jsoncount=0
set failedjson=0
set structuredcount=0
set failedstructured=0
set extractedcount=0
set failedextracted=0
set tempextractedcount=0
set failedtempextracted=0

echo Moving LOG files...
for %%f in ("logs\futures\*.log") do (
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
for %%f in ("logs\futures\*.zip") do (
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
    for %%f in ("logs\futures\debug\*.csv") do (
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

echo Moving TRADE CSV files...
for %%f in ("logs\futures\trades_*.csv") do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a tradescount+=1
        ) else (
            set /a failedtrades+=1
        )
    )
)

echo Moving ORDERS CSV files...
for %%f in ("logs\futures\orders_*.csv") do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a orderscount+=1
        ) else (
            set /a failedorders+=1
        )
    )
)

echo Moving POSITIONS_OPEN CSV files...
for %%f in ("logs\futures\positions_open_*.csv") do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a positionsopencount+=1
        ) else (
            set /a failedpositionsopen+=1
        )
    )
)

echo Moving SIGNALS CSV files...
for %%f in ("logs\futures\signals_*.csv") do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a signalscount+=1
        ) else (
            set /a failedsignals+=1
        )
    )
)

echo Moving JSON files...
for %%f in ("logs\trades_*.json") do (
    if exist "%%f" (
        move /Y "%%f" "!archivefolder!\" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a jsoncount+=1
        ) else (
            set /a failedjson+=1
        )
    )
)

echo Moving STRUCTURED JSON files...
if exist "logs\futures\structured" (
    for %%f in ("logs\futures\structured\*.json") do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 (
                set /a structuredcount+=1
            ) else (
                set /a failedstructured+=1
            )
        )
    )
)

echo Moving EXTRACTED files...
if exist "logs\futures\extracted" (
    for %%f in ("logs\futures\extracted\*.*") do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 (
                set /a extractedcount+=1
            ) else (
                set /a failedextracted+=1
            )
        )
    )
    rmdir "logs\futures\extracted" >nul 2>&1
)

echo Moving TEMP_EXTRACTED files...
if exist "logs\futures\temp_extracted" (
    for %%f in ("logs\futures\temp_extracted\*.*") do (
        if exist "%%f" (
            move /Y "%%f" "!archivefolder!\" >nul 2>&1
            if !errorlevel! equ 0 (
                set /a tempextractedcount+=1
            ) else (
                set /a failedtempextracted+=1
            )
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
echo Moved ORDERS CSV files: !orderscount!
echo Moved POSITIONS_OPEN CSV files: !positionsopencount!
echo Moved SIGNALS CSV files: !signalscount!
echo Moved JSON files: !jsoncount!
echo Moved STRUCTURED JSON files: !structuredcount!
echo Moved EXTRACTED files: !extractedcount!
echo Moved TEMP_EXTRACTED files: !tempextractedcount!
echo.
echo Failed to move: !failedcount! LOG, !failedzip! ZIP, !faileddebugcsv! DEBUG_CSV, !failedtrades! TRADE_CSV, !failedorders! ORDERS_CSV, !failedpositionsopen! POSITIONS_OPEN_CSV, !failedsignals! SIGNALS_CSV, !failedjson! JSON, !failedstructured! STRUCTURED, !failedextracted! EXTRACTED, !failedtempextracted! TEMP_EXTRACTED
echo.

set totalmoved=0
set /a totalmoved=!logcount!+!zipcount!+!debugcsvcount!+!tradescount!+!orderscount!+!positionsopencount!+!signalscount!+!jsoncount!+!structuredcount!+!extractedcount!+!tempextractedcount!

if !totalmoved! equ 0 (
    echo [WARNING] No files were moved!
    echo Removing empty archive folder...
    rmdir "!archivefolder!" >nul 2>&1
    echo Empty folder removed.
) else (
    echo Archive folder: !archivefolder!
    echo Total files moved: !totalmoved!
    echo.
    
    echo ====================================
    echo   CREATING ZIP ARCHIVE
    echo ====================================
    echo.
    
    set zipfile=logs\futures\archived\!datefolder!.zip
    
    echo Creating ZIP archive: !zipfile!
    echo.
    
    where powershell >nul 2>&1
    if !errorlevel! equ 0 (
        set "ps_archive_path=!archivefolder!"
        set "ps_zip_path=!zipfile!"
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path \"!ps_archive_path!\*\" -DestinationPath \"!ps_zip_path!\" -Force" >nul 2>&1
        if !errorlevel! equ 0 (
            echo [SUCCESS] ZIP archive created: !zipfile!
            
            for %%A in ("!zipfile!") do (
                set zipsize=%%~zA
                set /a zipsize_mb=!zipsize!/1024/1024
                echo Archive size: !zipsize_mb! MB
            )
            
            REM Опция: автоматически удалять исходную папку после создания ZIP
            REM Если нужно всегда удалять - раскомментируйте следующие строки:
            REM echo Removing archive folder (automatic)...
            REM rmdir /S /Q "!archivefolder!" >nul 2>&1
            REM if !errorlevel! equ 0 (
            REM     echo [SUCCESS] Archive folder removed.
            REM ) else (
            REM     echo [WARNING] Failed to remove archive folder. You can remove it manually.
            REM )
            
            REM Если нужно всегда оставлять - раскомментируйте:
            REM echo Keeping archive folder: !archivefolder!
            
            REM По умолчанию: спрашиваем пользователя
            echo.
            echo Do you want to remove the original archive folder?
            echo Press Y to remove, any other key to keep:
            set /p removefolder="[Y/N]: "
            if /i "!removefolder!"=="Y" (
                echo Removing archive folder...
                rmdir /S /Q "!archivefolder!" >nul 2>&1
                if !errorlevel! equ 0 (
                    echo [SUCCESS] Archive folder removed.
                ) else (
                    echo [WARNING] Failed to remove archive folder. You can remove it manually.
                )
            ) else (
                echo Keeping archive folder: !archivefolder!
            )
        ) else (
            echo [WARNING] Failed to create ZIP archive. Keeping archive folder.
            echo You can create ZIP manually or try again.
        )
    ) else (
        echo [WARNING] PowerShell not found. Cannot create ZIP archive.
        echo Archive folder kept: !archivefolder!
        echo You can create ZIP manually using 7-Zip or WinRAR.
    )
)

echo.
echo ====================================
echo   CLEAN LOGS COMPLETE
echo ====================================
echo.
echo Press any key to exit...
pause

