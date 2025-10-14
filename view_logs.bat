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

REM Find latest log file
for /f "delims=" %%i in ('dir /B /O-D logs\trading_bot_*.log 2^>nul') do (
    set "log_file=logs\%%i"
    goto :FOUND
)

REM If no log file found
echo Файлы логов не найдены!
echo Сначала запустите бота: start_bot.bat
echo.
pause
exit /b 1

:FOUND
echo Найден лог: %log_file%
for %%A in ("%log_file%") do echo Размер: %%~zA байт
echo.
echo =====================================
echo   ВЫБЕРИТЕ РЕЖИМ ПРОСМОТРА:
echo =====================================
echo.
echo 1. Последние 50 строк
echo 2. Последние 100 строк
echo 3. Весь лог (медленно для больших файлов!)
echo 4. Мониторинг в реальном времени
echo 5. Открыть в Notepad
echo 6. Только ошибки
echo 7. Только сигналы и сделки
echo 8. Статистика (текущий лог)
echo 9. Статистика (ВСЕ логи за день)
echo 0. Выход
echo.
set /p choice="Ваш выбор (0-9): "

if "%choice%"=="1" (
    cls
    echo =====================================
    echo   ПОСЛЕДНИЕ 50 СТРОК:
    echo =====================================
    echo.
    powershell -command "Get-Content '%log_file%' -Tail 50 -Encoding UTF8"
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
    powershell -command "Get-Content '%log_file%' -Tail 100 -Encoding UTF8"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="3" (
    cls
    echo =====================================
    echo   ВСЕ ЛОГИ (может быть медленно!):
    echo =====================================
    echo.
    type "%log_file%"
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
    powershell -command "Get-Content '%log_file%' -Wait -Tail 20 -Encoding UTF8"
    echo.
    echo Возврат в меню...
    timeout /t 2 >nul
    goto MENU
)

if "%choice%"=="5" (
    echo.
    echo Открываю лог в Notepad...
    start notepad "%log_file%"
    echo.
    echo Notepad запущен. Возврат в меню через 2 секунды...
    timeout /t 2 >nul
    goto MENU
)

if "%choice%"=="6" (
    cls
    echo =====================================
    echo   ТОЛЬКО ОШИБКИ:
    echo =====================================
    echo.
    findstr /C:"ERROR" /C:"WARNING" "%log_file%"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo Ошибок не найдено! Отлично!
    )
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
    findstr /C:"SIGNAL" /C:"POSITION" /C:"OPENED" /C:"CLOSED" /C:"executed" "%log_file%"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo Сигналов пока нет. Ожидаем рыночных условий...
    )
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="8" (
    cls
    echo =====================================
    echo   СТАТИСТИКА ТОРГОВЛИ:
    echo =====================================
    echo.
    echo Сгенерировано сигналов:
    findstr /C:"SIGNAL GENERATED" "%log_file%" 2>nul | find /C "SIGNAL"
    echo.
    echo Открыто позиций:
    findstr /C:"POSITION OPENED" "%log_file%" 2>nul | find /C "OPENED"
    echo.
    echo Закрыто позиций:
    findstr /C:"POSITION CLOSED" "%log_file%" 2>nul | find /C "CLOSED"
    echo.
    echo Выполнено Partial TP:
    findstr /C:"Partial TP executed" "%log_file%" 2>nul | find /C "executed"
    echo.
    echo Активирован Break-even:
    findstr /C:"Break-even" "%log_file%" 2>nul | find /C "Break-even"
    echo.
    echo Ошибок:
    findstr /C:"ERROR" "%log_file%" 2>nul | find /C "ERROR"
    echo.
    echo =====================================
    echo.
    echo Последние 10 важных событий:
    echo --------------------------------
    findstr /C:"SIGNAL" /C:"POSITION" /C:"OPENED" /C:"CLOSED" "%log_file%" 2>nul | powershell -command "$input | Select-Object -Last 10"
    echo.
    echo =====================================
    echo.
    pause
    goto MENU
)

if "%choice%"=="9" (
    cls
    echo =====================================
    echo   ВСЕ ФАЙЛЫ ЛОГОВ:
    echo =====================================
    echo.
    dir /B logs\trading_bot_*.log 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo Файлы логов не найдены!
    )
    echo.
    echo Текущий лог: %log_file%
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



