@echo off
chcp 65001 >nul 2>&1
title OKX Trading Bot - Log Analyzer
color 0B

REM Переходим в папку проекта
cd /d "%~dp0"

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден! Установите Python 3.8+
    pause
    exit /b 1
)

echo.
echo ========================================
echo   OKX Trading Bot - Log Analyzer
echo ========================================
echo.

REM Если переданы параметры - используем их, иначе показываем меню
if "%1"=="" (
    REM Интерактивное меню
    python logs\analyze_logs.py
) else if "%1"=="--quick" (
    REM Быстрый анализ
    python logs\analyze_logs.py --quick
) else if "%1"=="--date" (
    REM Анализ по дате
    python logs\analyze_logs.py --date %2
) else if "%1"=="--compare" (
    REM Сравнение сессий
    python logs\analyze_logs.py --compare %2 %3
) else (
    REM Все остальные параметры передаем как есть
    python logs\analyze_logs.py %*
)

pause

