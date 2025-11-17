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

REM ✅ ОБНОВЛЕНО: Поддержка новых функций
REM Если переданы параметры - используем их, иначе показываем меню
if "%1"=="" (
    REM Интерактивное меню
    python logs\analyze_logs.py
) else if "%1"=="--quick" (
    REM Быстрый анализ
    python logs\analyze_logs.py --quick
) else if "%1"=="--date" (
    REM Анализ по дате
    if "%2"=="" (
        echo ❌ Укажите дату: analyze.bat --date YYYY-MM-DD
        exit /b 1
    )
    python logs\analyze_logs.py --date %2 %3 %4 %5 %6
) else if "%1"=="--investor" (
    REM Отчет для инвесторов
    if "%2"=="" (
        echo Используется последняя сессия
        python logs\analyze_logs.py --investor
    ) else (
        python logs\analyze_logs.py --date %2 --investor
    )
) else if "%1"=="--developer" (
    REM Отчет для разработчиков
    if "%2"=="" (
        echo Используется последняя сессия
        python logs\analyze_logs.py --developer
    ) else (
        python logs\analyze_logs.py --date %2 --developer
    )
) else if "%1"=="--export-json" (
    REM Экспорт сделок в JSON
    if "%2"=="" (
        echo Используется последняя сессия
        python logs\analyze_logs.py --export-json
    ) else (
        python logs\analyze_logs.py --date %2 --export-json
    )
) else if "%1"=="--export-csv" (
    REM Экспорт сделок в CSV
    if "%2"=="" (
        echo Используется последняя сессия
        python logs\analyze_logs.py --export-csv
    ) else (
        python logs\analyze_logs.py --date %2 --export-csv
    )
) else if "%1"=="--archive" (
    REM Архивация логов
    python logs\analyze_logs.py --archive
) else if "%1"=="--compare" (
    REM Сравнение сессий
    if "%2"=="" (
        echo ❌ Укажите две даты: analyze.bat --compare YYYY-MM-DD YYYY-MM-DD
        exit /b 1
    )
    python logs\analyze_logs.py --compare %2 %3
) else (
    REM Все остальные параметры передаем как есть
    python logs\analyze_logs.py %*
)

pause

