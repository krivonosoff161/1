@echo off
chcp 65001 >nul
title OKX Trading Bot - Start
color 0A
echo =====================================
echo   START OKX Trading Bot
echo =====================================
echo.

REM Change to project directory
cd /d "%~dp0"

REM Check virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo.
    echo Create virtual environment with:
    echo python -m venv venv
    echo.
    pause
    exit /b 1
)

REM Check config.yaml exists
if not exist "config.yaml" (
    echo ERROR: config.yaml not found!
    echo.
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Check environment variables
if not defined OKX_API_KEY (
    echo WARNING: Environment variables not found!
    echo Loading from .env file...
)

REM Create logs folder if not exists
if not exist "logs" mkdir logs

echo.
echo =====================================
echo   CONFIGURATION:
echo =====================================
echo Trading pairs: BTC-USDT, ETH-USDT, SOL-USDT
echo Mode: DEMO (OKX Sandbox)
echo Risk per trade: 1%%
echo Max open positions: 3
echo =====================================
echo.

REM Start bot in DEMO mode
echo Starting bot in DEMO mode...
echo Press Ctrl+C to stop
echo.
echo =====================================
python run_bot.py --config config.yaml

REM If bot stopped
echo.
echo =====================================
echo Bot stopped.
echo =====================================
pause
