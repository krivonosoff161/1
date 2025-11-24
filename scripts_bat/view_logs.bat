@echo off
chcp 65001 >nul 2>&1
title OKX Trading Bot - View Logs
color 0B

REM Change to project directory
cd /d "%~dp0"

REM Check if logs folder exists
if not exist "logs" (
    echo ОШИБКА: Папка logs не найдена!
    echo Бот ещё не был запущен.
    echo.
    pause
    exit /b 1
)

:MENU
cls
echo =====================================
echo   ПРОСМОТР ЛОГОВ - OKX Торговый Бот
echo =====================================
echo.
echo Поиск файлов логов...
echo.

REM Find latest log file (новый путь: logs/futures/)
set "log_file="
for /f "delims=" %%i in ('dir /B /O-D logs\futures\futures_main_*.log 2^>nul') do (
    if not defined log_file set "log_file=logs\futures\%%i"
)

REM If no log file found
if not defined log_file (
    echo Файлы логов не найдены!
    echo Сначала запустите бота: start_bot.bat
    echo.
    pause
    exit /b 1
)

echo Найден лог: %log_file%
for %%A in ("%log_file%") do echo Размер: %%~zA байт
echo.
echo =====================================
echo   ВЫБЕРИТЕ РЕЖИМ ПРОСМОТРА:
echo =====================================
echo.
echo 1. Последние 50 строк
echo 2. Последние 100 строк
echo 3. Последние 200 строк
echo 4. Мониторинг в реальном времени
echo 5. Открыть в Notepad
echo 6. Только ошибки (ERROR)
echo 7. Только сигналы и сделки
echo 8. Profit Harvesting логи
echo 9. Статистика быстрая
echo 0. Выход
echo.
set /p choice="Ваш выбор (0-9): "

if "%choice%"=="1" (
    cls
    echo =====================================
    echo   ПОСЛЕДНИЕ 50 СТРОК:
    echo =====================================
    echo.
    powershell -NoProfile -Command "Get-Content '%log_file%' -Tail 50 -Encoding UTF8"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="2" (
    cls
    echo =====================================
    echo   ПОСЛЕДНИЕ 100 СТРОК:
    echo =====================================
    echo.
    powershell -NoProfile -Command "Get-Content '%log_file%' -Tail 100 -Encoding UTF8"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="3" (
    cls
    echo =====================================
    echo   ПОСЛЕДНИЕ 200 СТРОК:
    echo =====================================
    echo.
    powershell -NoProfile -Command "Get-Content '%log_file%' -Tail 200 -Encoding UTF8"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="4" (
    cls
    echo =====================================
    echo   МОНИТОРИНГ В РЕАЛЬНОМ ВРЕМЕНИ
    echo   Нажмите Ctrl+C для остановки
    echo =====================================
    echo.
    powershell -NoProfile -Command "Get-Content '%log_file%' -Wait -Tail 20 -Encoding UTF8"
    echo.
    goto MENU
)

if "%choice%"=="5" (
    echo.
    echo Открываю лог в Notepad...
    start notepad "%log_file%"
    echo.
    timeout /t 1 >nul
    goto MENU
)

if "%choice%"=="6" (
    cls
    echo =====================================
    echo   ТОЛЬКО ОШИБКИ:
    echo =====================================
    echo.
    powershell -NoProfile -Command "Get-Content '%log_file%' -Encoding UTF8 | Select-String 'ERROR|CRITICAL' | Select-Object -Last 50"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="7" (
    cls
    echo =====================================
    echo   ТОЛЬКО СИГНАЛЫ И СДЕЛКИ:
    echo =====================================
    echo.
    powershell -NoProfile -Command "Get-Content '%log_file%' -Encoding UTF8 | Select-String 'SIGNAL GENERATED|POSITION OPENED|TRADE CLOSED' | Select-Object -Last 30"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="8" (
    cls
    echo =====================================
    echo   PROFIT HARVESTING ЛОГИ:
    echo =====================================
    echo.
    echo PH Checks (последние 20):
    echo --------------------------------
    powershell -NoProfile -Command "Get-Content '%log_file%' -Encoding UTF8 | Select-String 'PH Check|PROFIT HARVESTING' | Select-Object -Last 20"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="9" (
    cls
    echo =====================================
    echo   СТАТИСТИКА БЫСТРАЯ:
    echo =====================================
    echo.
    echo Файл: %log_file%
    echo.
    
    powershell -NoProfile -Command "$content = Get-Content '%log_file%' -Encoding UTF8; $signals = ($content | Select-String 'SIGNAL GENERATED').Count; $opened = ($content | Select-String 'POSITION OPENED').Count; $closed = ($content | Select-String 'TRADE CLOSED').Count; $ph = ($content | Select-String 'PROFIT HARVESTING TRIGGERED').Count; $errors = ($content | Select-String 'ERROR').Count; Write-Host \"Сигналов: $signals\"; Write-Host \"Открыто: $opened\"; Write-Host \"Закрыто: $closed\"; Write-Host \"PH сработало: $ph\"; Write-Host \"Ошибок: $errors\""
    
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
    echo   До свидания!
    echo =====================================
    timeout /t 1 >nul
    exit /b 0
)

echo.
echo Неверный выбор! Попробуйте снова...
timeout /t 2 >nul
goto MENU
