@echo off
REM Запуск бота на 10 минут для тестирования
REM ВАЖНО: Нажать Ctrl+C после 10 минут чтобы собрать логи

echo ========================================
echo Starting Futures Trading Bot for 10 minutes
echo Press Ctrl+C after 10 minutes to stop
echo ========================================
echo.

cd /d "%~dp0"
python run.py --mode futures

echo.
echo ========================================
echo Bot stopped. Analyzing logs...
echo ========================================
timeout /t 5 /nobreak
