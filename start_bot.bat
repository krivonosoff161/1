@echo off
title OKX Trading Bot - Запуск
echo =====================================
echo   Запуск OKX Trading Bot
echo =====================================

REM Переход в папку проекта
cd /d "C:\Users\krivo\simple trading bot okx"

REM Проверяем, что папка существует
if not exist "venv\Scripts\activate.bat" (
    echo ОШИБКА: Виртуальное окружение не найдено!
    echo Убедитесь, что путь к проекту правильный.
    pause
    exit /b 1
)

REM Активируем виртуальное окружение
echo Активация виртуального окружения...
call venv\Scripts\activate.bat

REM Очищаем старые логи
echo Очистка старых логов...
if exist "logs\*.log" del /Q "logs\*.log"

REM Запускаем бота в тестовом режиме
echo Запуск бота в DRY-RUN режиме...
echo Для остановки нажмите Ctrl+C
echo =====================================
python run_bot.py --dry-run

REM Если бот остановился, показываем паузу
echo.
echo Бот остановлен.
pause