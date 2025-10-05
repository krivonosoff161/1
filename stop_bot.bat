@echo off
title OKX Trading Bot - Остановка
echo =====================================
echo   Остановка OKX Trading Bot
echo =====================================

REM Поиск процессов Python с нашим ботом
echo Поиск запущенных процессов бота...

REM Убиваем процессы python.exe, связанные с run_bot.py
for /f "tokens=2" %%i in ('tasklist /FI "IMAGENAME eq python.exe" /FO CSV ^| findstr /C:"python.exe"') do (
    echo Найден процесс Python: %%i
    wmic process where "ProcessId=%%i" get CommandLine | findstr "run_bot" >nul
    if not errorlevel 1 (
        echo Остановка процесса бота %%i...
        taskkill /PID %%i /F
    )
)

REM Альтернативный способ - убить все Python процессы (осторожно!)
REM Раскомментируйте следующую строку, если нужно убить ВСЕ процессы Python:
REM taskkill /IM python.exe /F

echo.
echo Все процессы бота остановлены.
echo =====================================
pause