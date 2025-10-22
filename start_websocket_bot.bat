@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title OKX Trading Bot - WebSocket Mode
color 0A
echo =====================================
echo   START OKX Trading Bot - WebSocket
echo =====================================
echo.

REM Проверяем, не запущен ли уже бот
tasklist /FI "IMAGENAME eq python.exe" 2>nul | find /I "run_bot.py" >nul
if !ERRORLEVEL! EQU 0 (
    echo WARNING: Bot is already running!
    echo Please stop it first with stop_bot.bat
    echo.
    pause
    exit /b 1
)

REM Проверяем наличие виртуального окружения
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo Please run: python -m venv venv
    echo Then install requirements: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM Активируем виртуальное окружение
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Проверяем, что активация прошла успешно
if !ERRORLEVEL! NEQ 0 (
    echo ERROR: Failed to activate virtual environment!
    pause
    exit /b 1
)

REM Проверяем наличие файла конфигурации
if not exist "config.yaml" (
    echo ERROR: config.yaml not found!
    echo Please create configuration file first.
    echo.
    pause
    exit /b 1
)

REM Создаем lock файл
echo %date% %time% > bot_websocket.lock

REM Запускаем бота в WebSocket режиме
echo.
echo Starting bot in WebSocket mode...
echo Press Ctrl+C to stop the bot
echo.

python run_bot.py --mode websocket

REM Удаляем lock файл при завершении
if exist bot_websocket.lock del bot_websocket.lock

echo.
echo Bot stopped.
pause

