@echo off
chcp 65001 >nul 2>&1
title OKX Trading Bot - Exit Decisions Analyzer
color 0B

REM Переходим в папку проекта
cd /d "%~dp0\.."

REM Проверяем наличие Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден! Установите Python 3.8+
    pause
    exit /b 1
)

echo.
echo ========================================
echo   OKX Trading Bot - Exit Decisions Analyzer
echo ========================================
echo.

REM Анализ решений ExitAnalyzer из JSON файлов
if "%1"=="" (
    REM Интерактивное меню
    python -c "import json; from pathlib import Path; files = list(Path('logs/futures/debug/exit_decisions').glob('*.json')); print(f'Найдено файлов: {len(files)}'); [print(f\"  {f.name}\") for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[:10]]"
    echo.
    echo Используйте: analyze_exit_decisions.bat --symbol BTC-USDT
    echo Или: analyze_exit_decisions.bat --all
) else if "%1"=="--all" (
    REM Анализ всех решений
    python -c "import json; from pathlib import Path; from collections import Counter; files = list(Path('logs/futures/debug/exit_decisions').glob('*.json')); decisions = [json.load(open(f)) for f in files]; actions = Counter(d['decision'] for d in decisions); print('Распределение решений:'); [print(f'  {action}: {count}') for action, count in actions.most_common()]"
) else if "%1"=="--symbol" (
    REM Анализ для символа
    if "%2"=="" (
        echo ❌ Укажите символ: analyze_exit_decisions.bat --symbol BTC-USDT
        exit /b 1
    )
    python -c "import json; from pathlib import Path; files = [f for f in Path('logs/futures/debug/exit_decisions').glob('*.json') if '%2' in f.name]; decisions = [json.load(open(f)) for f in files]; print(f'Решения для %2: {len(decisions)}'); [print(f\"  {d.get('timestamp')}: {d.get('decision')} - {d.get('reason')}\") for d in sorted(decisions, key=lambda x: x.get('timestamp', ''), reverse=True)[:20]]"
) else (
    echo Неизвестный параметр: %1
    echo Использование:
    echo   analyze_exit_decisions.bat --all
    echo   analyze_exit_decisions.bat --symbol BTC-USDT
)

echo.
pause

