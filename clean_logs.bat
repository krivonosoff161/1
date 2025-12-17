@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Clean Logs

REM ============================================================
REM clean_logs.bat (safe)
REM - Creates ONE zip with all current logs/csv/json
REM - Deletes originals (move into staging -> zip -> delete staging)
REM - Supports:
REM     --dry      : show what would be moved/zipped (no changes)
REM     --nopause  : do not pause at the end
REM ============================================================

set "DRY=0"
set "NOPAUSE=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--dry" set "DRY=1"
if /I "%~1"=="--nopause" set "NOPAUSE=1"
shift
goto parse_args

:args_done

cd /d "%~dp0" || (echo [ERROR] Failed to cd to script dir: "%~dp0" & goto end_fail)

REM Timestamp (PowerShell)
set "TS="
for /f "delims=" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss" 2^>nul') do set "TS=%%I"
if not defined TS echo [ERROR] Failed to get timestamp (PowerShell failed). & goto end_fail

set "ARCHIVE_DIR=logs\futures\archived"
set "STAGE_DIR=%ARCHIVE_DIR%\staging_%TS%"
set "ZIP_FILE=%ARCHIVE_DIR%\logs_%TS%.zip"

if "%DRY%"=="1" (
  echo [DRY RUN] No files will be moved or deleted.
) else (
  if not exist "%ARCHIVE_DIR%" mkdir "%ARCHIVE_DIR%" >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Cannot create archive dir: "%ARCHIVE_DIR%"
    goto end_fail
  )
  if not exist "%STAGE_DIR%" mkdir "%STAGE_DIR%" >nul 2>&1
  if errorlevel 1 (
    echo [ERROR] Cannot create staging dir: "%STAGE_DIR%"
    goto end_fail
  )
)

echo ====================================
echo CLEAN LOGS
echo ====================================
echo Timestamp : %TS%
echo Zip file  : %ZIP_FILE%
echo Stage dir : %STAGE_DIR%
echo Dry run   : %DRY%
echo.

set "MOVED=0"
set "SKIPPED=0"

call :move_pattern logs\futures\*.log
call :move_pattern logs\futures\*.zip
call :move_pattern logs\futures\debug\*.csv
call :move_pattern logs\futures\structured\*.json

call :move_pattern logs\trades_*.csv
call :move_pattern logs\trades_*.json
call :move_pattern logs\orders_*.csv
call :move_pattern logs\positions_open_*.csv
call :move_pattern logs\signals_*.csv
call :move_pattern logs\*.log
call :move_pattern logs\*.zip

call :move_folder logs\extracted logs_extracted
call :move_folder logs\reports logs_reports
call :move_folder logs\spot logs_spot

echo.
echo Moved files : %MOVED%
echo Skipped    : %SKIPPED%
echo.

if "%DRY%"=="1" goto end_ok

if %MOVED% LEQ 0 (
  echo [WARNING] No files were moved. Removing empty staging dir.
  rmdir "%STAGE_DIR%" >nul 2>&1
  goto end_ok
)

where powershell >nul 2>&1
if errorlevel 1 (
  echo [ERROR] PowerShell not found. Cannot create zip automatically.
  echo Stage folder kept: "%STAGE_DIR%"
  goto end_fail
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%STAGE_DIR%\*' -DestinationPath '%ZIP_FILE%' -Force" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Failed to create zip: "%ZIP_FILE%"
  echo Stage folder kept: "%STAGE_DIR%"
  goto end_fail
)

echo [OK] Zip created: %ZIP_FILE%

rmdir /S /Q "%STAGE_DIR%" >nul 2>&1
if errorlevel 1 (
  echo [WARNING] Failed to remove staging folder: "%STAGE_DIR%"
) else (
  echo [OK] Staging folder removed.
)

goto end_ok

:move_pattern
set "PAT=%~1"
for %%F in (%PAT%) do (
  if exist "%%F" (
    if "%DRY%"=="1" (
      echo [DRY] move "%%F" "%STAGE_DIR%\"
      set /a MOVED+=1
    ) else (
      move /Y "%%F" "%STAGE_DIR%\" >nul 2>&1
      if errorlevel 1 (
        echo [WARN] Failed to move: %%F
        set /a SKIPPED+=1
      ) else (
        set /a MOVED+=1
      )
    )
  )
)
exit /b 0

:move_folder
set "SRC=%~1"
set "DSTSUB=%~2"
if not exist "%SRC%\" exit /b 0

where robocopy >nul 2>&1
if errorlevel 1 (
  echo [WARN] robocopy not found, skipping folder: %SRC%
  exit /b 0
)

if "%DRY%"=="1" (
  echo [DRY] robocopy "%SRC%" "%STAGE_DIR%\%DSTSUB%" /E /MOVE
  exit /b 0
)

robocopy "%SRC%" "%STAGE_DIR%\%DSTSUB%" /E /MOVE /NFL /NDL /NJH /NJS /NP >nul
REM robocopy: exit codes LT 8 are success
if %errorlevel% GEQ 8 (
  echo [WARN] robocopy reported issues for folder: %SRC% (code=%errorlevel%)
)
rmdir "%SRC%" >nul 2>&1
exit /b 0

:end_ok
echo.
echo Done.
if "%NOPAUSE%"=="1" exit /b 0
pause
exit /b 0

:end_fail
echo.
echo Failed.
if "%NOPAUSE%"=="1" exit /b 1
pause
exit /b 1


