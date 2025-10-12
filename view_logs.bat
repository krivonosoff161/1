@echo off
chcp 65001 >nul 2>&1
title OKX Trading Bot - View Logs
color 0B

REM Change to project directory
cd /d "%~dp0"

REM Check if logs folder exists
if not exist "logs" (
    echo ERROR: Logs folder not found!
    echo Bot has not been started yet.
    echo.
    pause
    exit /b 1
)

:MENU
cls
echo =====================================
echo   VIEW LOGS - OKX Trading Bot
echo =====================================
echo.
echo Searching for log files...
echo.

REM Find latest log file
for /f "delims=" %%i in ('dir /B /O-D logs\trading_bot_*.log 2^>nul') do (
    set "log_file=logs\%%i"
    goto :FOUND
)

REM If no log file found
echo Log files not found!
echo Please start the bot first: start_bot.bat
echo.
pause
exit /b 1

:FOUND
echo Found log: %log_file%
for %%A in ("%log_file%") do echo Size: %%~zA bytes
echo.
echo =====================================
echo   SELECT VIEW MODE:
echo =====================================
echo.
echo 1. Show last 50 lines
echo 2. Show last 100 lines
echo 3. Show all logs
echo 4. Real-time monitoring
echo 5. Open in Notepad
echo 6. Show only errors
echo 7. Show only signals
echo 8. Show statistics
echo 9. Show all log files
echo 0. Exit
echo.
set /p choice="Your choice (0-9): "

if "%choice%"=="1" (
    cls
    echo =====================================
    echo   LAST 50 LINES:
    echo =====================================
    echo.
    powershell -command "Get-Content '%log_file%' -Tail 50 -Encoding UTF8"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="2" (
    cls
    echo =====================================
    echo   LAST 100 LINES:
    echo =====================================
    echo.
    powershell -command "Get-Content '%log_file%' -Tail 100 -Encoding UTF8"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="3" (
    cls
    echo =====================================
    echo   ALL LOGS:
    echo =====================================
    echo.
    type "%log_file%"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="4" (
    cls
    echo =====================================
    echo   REAL-TIME MONITORING
    echo   Press Ctrl+C to stop
    echo =====================================
    echo.
    powershell -command "Get-Content '%log_file%' -Wait -Tail 20 -Encoding UTF8"
    echo.
    echo Returning to menu...
    timeout /t 2 >nul
    goto MENU
)

if "%choice%"=="5" (
    echo.
    echo Opening log in Notepad...
    start notepad "%log_file%"
    echo.
    echo Notepad opened. Returning to menu in 2 seconds...
    timeout /t 2 >nul
    goto MENU
)

if "%choice%"=="6" (
    cls
    echo =====================================
    echo   ERRORS ONLY:
    echo =====================================
    echo.
    findstr /C:"ERROR" "%log_file%"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo No errors found! Excellent!
    )
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="7" (
    cls
    echo =====================================
    echo   SIGNALS ONLY:
    echo =====================================
    echo.
    findstr /C:"SIGNAL" /C:"POSITION" /C:"OPENED" /C:"CLOSED" /C:"executed" "%log_file%"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo No signals yet. Waiting for market conditions...
    )
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="8" (
    cls
    echo =====================================
    echo   TRADING STATISTICS:
    echo =====================================
    echo.
    echo Generated signals:
    findstr /C:"SIGNAL GENERATED" "%log_file%" 2>nul | find /C "SIGNAL"
    echo.
    echo Opened positions:
    findstr /C:"POSITION OPENED" "%log_file%" 2>nul | find /C "OPENED"
    echo.
    echo Closed positions:
    findstr /C:"POSITION CLOSED" "%log_file%" 2>nul | find /C "CLOSED"
    echo.
    echo Partial TP executed:
    findstr /C:"Partial TP executed" "%log_file%" 2>nul | find /C "executed"
    echo.
    echo Break-even activated:
    findstr /C:"Break-even" "%log_file%" 2>nul | find /C "Break-even"
    echo.
    echo Errors:
    findstr /C:"ERROR" "%log_file%" 2>nul | find /C "ERROR"
    echo.
    echo =====================================
    echo.
    echo Last 10 important events:
    echo --------------------------------
    findstr /C:"SIGNAL" /C:"POSITION" /C:"OPENED" /C:"CLOSED" "%log_file%" 2>nul | powershell -command "$input | Select-Object -Last 10"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="9" (
    cls
    echo =====================================
    echo   ALL LOG FILES:
    echo =====================================
    echo.
    dir /B logs\trading_bot_*.log 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo Log files not found!
    )
    echo.
    echo Current log: %log_file%
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="0" (
    cls
    echo.
    echo =====================================
    echo   Goodbye!
    echo =====================================
    timeout /t 1 >nul
    exit /b 0
)

echo.
echo Invalid choice! Please try again...
timeout /t 2 >nul
goto MENU



