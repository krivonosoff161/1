@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title Trading Bot Launcher

REM Go to project root directory (where this bat file is located)
cd /d "%~dp0"

echo.
echo ================================================================
echo              TRADING BOT LAUNCHER
echo.
echo   Windows Launcher for Trading Bot
echo   Supports Spot and Futures trading
echo ================================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo [INFO] Install Python 3.8+ and add to PATH
    echo [INFO] Download from https://python.org
    pause
    exit /b 1
)

REM Check virtual environment
set PYTHON_EXE=python
if exist "venv\Scripts\python.exe" (
    echo [OK] Virtual environment found
    set PYTHON_EXE=venv\Scripts\python.exe
) else (
    echo [WARNING] Virtual environment not found
    echo [INFO] Recommended: create virtual environment
    echo    python -m venv venv
    echo    venv\Scripts\activate
    echo    pip install -r requirements.txt
    echo.
    set /p venv_choice="Continue without virtual environment? (y/n): "
    if /i "!venv_choice!" neq "y" (
        echo [INFO] Launch cancelled
        pause
        exit /b 0
    )
)

REM Check dependencies
echo [CHECK] Checking dependencies...
%PYTHON_EXE% -c "import loguru, aiohttp, pydantic" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Dependencies not installed!
    echo [INFO] Install: pip install -r requirements.txt
    pause
    exit /b 1
)

REM Check config files
echo [CHECK] Checking configuration...
if not exist "config\config_spot.yaml" (
    echo [ERROR] Config file config\config_spot.yaml not found!
    echo [INFO] Create config file for Spot trading
    pause
    exit /b 1
)

if not exist "config\config_futures.yaml" (
    echo [ERROR] Config file config\config_futures.yaml not found!
    echo [INFO] Create config file for Futures trading
    pause
    exit /b 1
)

echo [OK] Configuration files found

REM Create log directories
if not exist "logs\spot" mkdir "logs\spot"
if not exist "logs\futures" mkdir "logs\futures"

echo.
echo Select trading mode:
echo 1. Spot Trading
echo 2. Futures Trading
echo 3. Check configuration
echo 4. Exit
echo.

:menu
set /p choice="Enter number (1-4): "

if "%choice%"=="1" goto spot_mode
if "%choice%"=="2" goto futures_mode
if "%choice%"=="3" goto check_config
if "%choice%"=="4" goto exit
echo [ERROR] Invalid choice. Try again.
goto menu

:spot_mode
echo.
echo ================================================================
echo              SPOT TRADING MODE
echo.
echo   Spot Trading Features:
echo   - Trading without leverage (1:1)
echo   - Lower risks
echo   - Suitable for beginners
echo   - Lower PnL volatility
echo ================================================================
echo.
set /p confirm="Continue with Spot trading? (y/n): "
if /i "%confirm%" neq "y" goto menu

echo [START] Starting Spot trading bot...
%PYTHON_EXE% src\main_spot.py
if errorlevel 1 (
    echo [ERROR] Error starting Spot bot
    pause
)
goto end

:futures_mode
echo.
echo ================================================================
echo              FUTURES TRADING MODE
echo.
echo   Futures Trading Features:
echo   - Trading with leverage (5x default)
echo   - High risks and potential returns
echo   - Requires trading experience
echo   - Liquidation protection
echo.
echo   [WARNING] CRITICALLY IMPORTANT:
echo   - Configure correct margin thresholds
echo   - Use sandbox for testing
echo   - Start with minimum amounts
echo ================================================================
echo.
echo [WARNING] Futures trading involves high risks!
set /p confirm="Are you sure you want to continue? (y/n): "
if /i "%confirm%" neq "y" goto menu

echo [START] Starting Futures trading bot...
%PYTHON_EXE% src\main_futures.py
if errorlevel 1 (
    echo [ERROR] Error starting Futures bot
    pause
)
goto end

:check_config
echo [CHECK] Checking configuration...
%PYTHON_EXE% -c "from src.config import load_config; print('[OK] Configuration valid')"
echo.
pause
goto menu

:exit
echo [INFO] Goodbye!
goto end

:end
echo.
echo [OK] Trading bot stopped
echo [INFO] Logs saved in logs\ folder
echo.
pause
